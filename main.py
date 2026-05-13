import asyncio
import logging
import sys

from automation_server_client import (
    AutomationServer,
    Workqueue,
    WorkItemError,
    Credential,
    WorkItemStatus,
)
from datetime import datetime, timedelta, timezone
from kmd_nexus_client import NexusClientManager
from odk_tools.tracking import Tracker
from process.nexus_service import NexusService

nexus: NexusClientManager
tracker: Tracker
nexus_service: NexusService
proces_navn = "Afslutning af borgere i genoptræning"


async def populate_queue(workqueue: Workqueue):
    aktivitetsliste = nexus.aktivitetslister.hent_aktivitetsliste(
        navn="Robot - afslut genoptræningsforløb SUL § 140",
        organisation=None,
        medarbejder=None,
        antal_sider=10,
    )

    if aktivitetsliste is None:
        return

    aktivitetsliste = [
        aktivitet
        for aktivitet in aktivitetsliste
        if aktivitet.get("name") == "Robot - afslut genoptræningsforløb SUL § 140"
        and aktivitet["status"] == "Aktiv"
        and datetime.strptime(aktivitet["date"], "%Y-%m-%dT%H:%M:%S.%f%z")
        > datetime.now(timezone.utc) - timedelta(days=7)
    ]

    if aktivitetsliste:
        for aktivitet in aktivitetsliste:
            eksisterende_kødata = workqueue.get_item_by_reference(str(aktivitet["id"]))

            if (
                len(eksisterende_kødata) > 0
                or aktivitet["description"] == "Myndighed genoptræning"
            ):
                continue

            workqueue.add_item(aktivitet, str(aktivitet["id"]))


async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    for item in workqueue:
        with item:
            opgave_lukket = False
            data = item.data  # Item data deserialized from json as dict
            leverandørnavn = data["description"]
            opgave = nexus.hent_fra_reference(data)            

            opgave_skema = nexus.nexus_client.get(
                    data["children"][0]
                    .get("_links")
                    .get("referencedObject")
                    .get("href")
                ).json()
            opgave_skema = nexus.hent_fra_reference(opgave_skema)

            try:
                # TODO: Tilret til rigtige CPR-numre
                # borger = nexus.borgere.hent_borger(
                #     data["patients"][0]["patientIdentifier"]["identifier"]
                # )

                # Test CPR-nummer
                borger = nexus.borgere.hent_borger("010490-9989")

                if borger is None:
                    continue

                udenbys_borger = nexus_service.kontroller_udenbys_borger(borger=borger, opgave_skema=opgave_skema)

                if udenbys_borger:                    
                    continue
                
                if nexus_service.er_der_flere_genoptræningsplaner(
                    borger=borger,
                    opgave_skema=opgave_skema,
                    leverandørnavn=leverandørnavn,
                ):
                    continue

                nexus_service.kontroller_aktive_hjælpemidler(
                    borger=borger, leverandørnavn=leverandørnavn
                )

                nexus_service.fjern_relationer_og_inaktiver_tilstande(borger=borger)
                nexus_service.afslut_indsatser(borger=borger)
                nexus_service.afslut_skemaer(borger=borger)                
                nexus_service.fjern_medarbejdere(borger=borger)
                nexus_service.afslut_forløbsindplacering(borger=borger)

                if not nexus_service.afslut_forløb(borger=borger):
                    tracker.track_partial_task(process_name=proces_navn)
                    continue

                nexus_service.fjern_organisationstilknytning(
                    borger=borger, leverandørnavn=leverandørnavn
                )

                nexus.opgaver.luk_opgave(opgave)
                opgave_lukket = True
                tracker.track_task(proces_navn)

            except WorkItemError as e:                
                # A WorkItemError represents a soft error that indicates the item should be passed to manual processing or a business logic fault
                logger.error(f"Error processing item: {data}. Error: {e}")
                item.fail(str(e))
                
            finally:
                if not opgave_lukket:
                    nexus.opgaver.luk_opgave(opgave)
                    tracker.track_partial_task(process_name=proces_navn)
                


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    ats = AutomationServer.from_environment()
    workqueue = ats.workqueue()

    nexus_credential = Credential.get_credential("KMD Nexus - produktion")
    tracking_credential = Credential.get_credential("Odense SQL Server")

    tracker = Tracker(
        username=tracking_credential.username, password=tracking_credential.password
    )

    nexus = NexusClientManager(
        client_id=nexus_credential.username,
        client_secret=nexus_credential.password,
        instance=nexus_credential.data["instance"],
    )
    nexus_service = NexusService(nexus=nexus, tracker=tracker)

    tracker = Tracker(
        username=tracking_credential.username, password=tracking_credential.password
    )

    # Queue management
    if "--queue" in sys.argv:
        workqueue.clear_workqueue(WorkItemStatus.NEW)
        asyncio.run(populate_queue(workqueue))
        exit(0)

    # Process workqueue
    asyncio.run(process_workqueue(workqueue))
