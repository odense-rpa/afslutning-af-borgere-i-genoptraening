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


async def populate_queue(workqueue: Workqueue):
    aktivitetsliste = nexus.aktivitetslister.hent_aktivitetsliste(
        navn="Opgaver: Robot - alle opgavetyper robotten håndterer",
        organisation=None,
        medarbejder=None,
        antal_sider=10,
    )

    if aktivitetsliste is None:
        return

    aktivitetsliste = [
        aktivitet
        for aktivitet in aktivitetsliste
        if aktivitet.get("name") == "Robot - afslut borger"
        and aktivitet["status"] == "Aktiv"
        and datetime.strptime(aktivitet["date"], "%Y-%m-%dT%H:%M:%S.%f%z")
        > datetime.now(timezone.utc) - timedelta(days=7)
    ]

    if aktivitetsliste:
        for aktivitet in aktivitetsliste:
            eksisterende_kødata = workqueue.get_item_by_reference(str(aktivitet["id"]))

            if len(eksisterende_kødata) > 0:
                continue

            workqueue.add_item(aktivitet, str(aktivitet["id"]))


async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)
    logger.info("Hello from process workqueue!")

    for item in workqueue:
        with item:
            data = item.data  # Item data deserialized from json as dict
            leverandørnavn = data["description"]
            fejlbesked = ""

            try:
                borger = nexus.borgere.hent_borger(
                    data["patients"][0]["patientIdentifier"]["identifier"]
                )

                if borger is None:
                    continue

                fejlbesked = nexus_service.afslut_indsatser(
                    borger=borger, leverandørnavn=leverandørnavn
                )

                if fejlbesked:
                    # Exit tidligt pga. evt. udenbys borger
                    nexus_service.afslut_opgave(
                        borger=borger,
                        leverandørnavn=leverandørnavn,
                        opgave_reference=data,
                        fejl_beskrivelse=fejlbesked,
                    )
                    continue

                nexus_service.afslut_skemaer(
                    borger=borger, leverandørnavn=leverandørnavn
                )

                nexus_service.fjern_organisationstilknytning(
                    borger=borger, leverandørnavn=leverandørnavn
                )

                fejlbesked = nexus_service.kontroller_myndighedsindsatser(
                    borger=borger, leverandørnavn=leverandørnavn
                )

                nexus_service.afslut_opgave(
                    borger=borger,
                    leverandørnavn=leverandørnavn,
                    opgave_reference=data,
                    fejl_beskrivelse=fejlbesked,
                )

            except WorkItemError as e:
                # A WorkItemError represents a soft error that indicates the item should be passed to manual processing or a business logic fault
                logger.error(f"Error processing item: {data}. Error: {e}")
                item.fail(str(e))


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
