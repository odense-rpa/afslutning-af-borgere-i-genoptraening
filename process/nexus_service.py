from datetime import datetime, timedelta
from kmd_nexus_client import NexusClientManager
from kmd_nexus_client.tree_helpers import filter_by_path
from odk_tools.tracking import Tracker


class NexusService:
    def __init__(
        self,
        nexus: NexusClientManager,
        tracker: Tracker,
    ):
        self.nexus = nexus
        self.tracker = tracker

    
    def afslut_indsatser(self, borger: dict, leverandørnavn: str) -> str:
        pathway = self.nexus.borgere.hent_visning(borger=borger)
        fejl_besked = ""

        if pathway is None:
            raise ValueError(
                f"Kunne ikke finde -Alt for borger {borger['patientIdentifier']['identifier']}"
            )

        referencer = self.nexus.borgere.hent_referencer(visning=pathway)

        filtrerede_indsats_referencer = filter_by_path(
            referencer,
            path_pattern="/Sundhedsfagligt grundforløb/FSIII/Indsatser/Genoptræning udenbys borger (SUL § 140)",
            active_pathways_only=True,
        )

        if len(filtrerede_indsats_referencer) > 0:
            return "Udenbys - Robot"

        filtrerede_indsats_referencer = filter_by_path(
            referencer,
            path_pattern="/Sundhedsfagligt grundforløb/FSIII/Indsatser/basketGrantReference",
            active_pathways_only=True,
        )

        indsatser_referencer = self.nexus.indsatser.filtrer_indsats_referencer(
            indsats_referencer=filtrerede_indsats_referencer,
            kun_aktive=True,
            leverandør_navn=leverandørnavn,
        )

        for indsats_reference in indsatser_referencer:
            indsats = self.nexus.hent_fra_reference(indsats_reference)

            try:
                if indsats["workflowState"]["name"] == "Tildelt":
                    self.nexus.indsatser.rediger_indsats(
                        indsats=indsats, ændringer={}, overgang="Fjern"
                    )
                else:
                    self.nexus.indsatser.rediger_indsats(
                        indsats=indsats, ændringer={}, overgang="Afslut"
                    )

            except Exception:
                return "Slut - Robot"

        return fejl_besked

    def afslut_skemaer(self, borger: dict, leverandørnavn: str):
        pathway = self.nexus.borgere.hent_visning(borger=borger)

        if pathway is None:
            raise ValueError(
                f"Kunne ikke finde -Alt for borger {borger['patientIdentifier']['identifier']}"
            )

        referencer = self.nexus.borgere.hent_referencer(visning=pathway)

        filtrerede_skema_referencer = filter_by_path(
            referencer,
            path_pattern="/Sundhedsfagligt grundforløb/FSIII/formDataV2Reference",
            active_pathways_only=True,
        )

        aktive_skemaer = [
            skema_ref
            for skema_ref in filtrerede_skema_referencer
            if skema_ref.get("formDataStatus") == "Aktivt"
            and skema_ref.get("name") != "Generelle oplysninger"
        ]

        for skema_reference in aktive_skemaer:
            skema = self.nexus.hent_fra_reference(skema_reference)

            historik = self.nexus.skemaer.hent_skema_historik(skema=skema)
            leverandør_audit = sorted(
                historik, key=lambda entry: entry["date"], reverse=False
            )

            if len(leverandør_audit) > 0:
                primary_org = leverandør_audit[0]["professional"].get(
                    "primaryOrganization"
                )
                
                if primary_org and primary_org.get("name") == leverandørnavn:
                    # Fjern skemaets relationer
                    relationer = self.nexus.nexus_client.get(
                        skema["_links"]["relatedActivities"]["href"]
                    ).json()

                    for relation in relationer:
                        try:
                            self.nexus.nexus_client.delete(
                                relation["_links"]["deleteActivityLink"]["href"]
                            )
                        except Exception:
                            continue

                    # Sæt skema til inaktivt
                    self.nexus.skemaer.rediger_skema(skema, "Inaktivt", data={})

    def fjern_organisationstilknytning(self, borger: dict, leverandørnavn: str):
        relationer = self.nexus.organisationer.hent_organisationer_for_borger(
            borger=borger
        )
        for relation in relationer:
            if relation["organization"]["name"] == leverandørnavn:
                self.nexus.organisationer.fjern_borger_fra_organisation(
                    organisations_relation=relation
                )

    def kontroller_myndighedsindsatser(self, borger: dict, leverandørnavn: str) -> str:
        pathway = self.nexus.borgere.hent_visning(borger=borger)

        if pathway is None:
            raise ValueError(
                f"Kunne ikke finde -Alt for borger {borger['patientIdentifier']['identifier']}"
            )

        referencer = self.nexus.borgere.hent_referencer(visning=pathway)

        filtrerede_indsats_referencer = filter_by_path(
            referencer,
            path_pattern="/Sundhedsfagligt grundforløb/FSIII/Indsatser/basketGrantReference",
            active_pathways_only=False,
        )

        # Check GGOP
        ggop_indsatser_referencer = self.nexus.indsatser.filtrer_indsats_referencer(
            indsats_referencer=filtrerede_indsats_referencer,
            kun_aktive=True,
            leverandør_navn="GGOP til anden kommune",
        )

        if len(ggop_indsatser_referencer) > 0:
            return "GGOP - Robot"

        # Check andre genoptræningscentre
        genoptrænings_organisationer = [
            "Genoptræning Team Nord",
            "Genoptræning Team Syd",
            "Genoptræning Team Odense",
            "Rehabilitering og palliation",
        ]

        for leverandørnavn in genoptrænings_organisationer:
            indsatser_referencer = self.nexus.indsatser.filtrer_indsats_referencer(
                indsats_referencer=filtrerede_indsats_referencer,
                kun_aktive=True,
                leverandør_navn=leverandørnavn,
            )

            if len(indsatser_referencer) > 0:
                return "Slut - Robot"

        # Check forløbsindplaceringer
        forløbs_indplacerings_referencer = filter_by_path(
            referencer,
            path_pattern="/ÆHF - Forløbsindplacering (Grundforløb)/Forløbsindplacering/Indsatser/basketGrantReference",
            active_pathways_only=True,
        )

        aktive_forløbs_indplacerings_referencer = (
            self.nexus.indsatser.filtrer_indsats_referencer(
                indsats_referencer=forløbs_indplacerings_referencer,
                kun_aktive=True,
            )
        )

        if len(aktive_forløbs_indplacerings_referencer) > 0:
            return "Slut - Robot"

        # Check hjælpemidler
        hjaelpemiddelsindsatser = [
            "SEL § 86 Træning Hjælpemidler",
            "SUL § 140 Træning Hjælpemidler",
            "ÆL § 9 Træning Hjælpemidler",
        ]

        aktive_udlån = self.nexus.borgere.hent_udlån(borger=borger)

        if aktive_udlån is not None:
            for udlån in aktive_udlån:
                grant = udlån.get("grant") or {}
                if grant.get("name") in hjaelpemiddelsindsatser:
                    self.nexus.opgaver.opret_opgave(
                        objekt=udlån,
                        opgave_type="Opfølgning på udlån af træningsredskab",
                        titel="Opfølgning på udlån af træningsredskab",
                        ansvarlig_organisation=leverandørnavn,
                        start_dato=datetime.now().date(),
                        forfald_dato=datetime.now().date(),
                        beskrivelse=""""I forbindelse med afslutning af borgerens træningsforløb, er det konstateret, at der fortsat er aktive udlån af træningsredskaber fra Hjælpemiddelservice. 
                                        I bedes derfor følge op på disse udlån i forhold til følgende muligheder:
                                        
                                        •	Bestil hjemtagning i Nexus (efter forudgående aftale med borger)
                                        •	Kontakt Myndighed for forespørgsel om overflytning til SEL § 112 – varig bevilling
                                        •	Bestil hjemtagning af de redskaber, som Myndighed ikke kan bevilge.
                                        •	Kontakt Hjælpemiddelservice, hvis der er tale om hjælpemidler, der foreslås kasseret (f.eks. ikke genbrugelige kiler)""",
                    )

        return ""

    def afslut_opgave(
        self,
        borger: dict,
        leverandørnavn: str,
        opgave_reference: dict,
        fejl_beskrivelse: str,
    ):
        if fejl_beskrivelse:
            pathway = self.nexus.borgere.hent_visning(borger=borger)

            if pathway is None:
                raise ValueError(
                    f"Kunne ikke finde -Alt for borger {borger['patientIdentifier']['identifier']}"
                )

            referencer = self.nexus.borgere.hent_referencer(visning=pathway)

            skema_referencer = filter_by_path(
                referencer,
                path_pattern="/Sundhedsfagligt grundforløb/FSIII/formDataV2Reference",
                active_pathways_only=True,
            )

            slutnotat_referencer = [
                skema_ref
                for skema_ref in skema_referencer
                if skema_ref.get("name") == "Slutnotat træning"
            ]
            slutnotat_referencer.sort(key=lambda x: x.get("date", ""), reverse=True)

            if len(slutnotat_referencer) > 0:
                slutnotat = self.nexus.hent_fra_reference(slutnotat_referencer[0])
                self.nexus.opgaver.opret_opgave(
                    objekt=slutnotat,
                    opgave_type="Tværfagligt samarbejde",
                    titel=fejl_beskrivelse,
                    ansvarlig_organisation="Myndighed genoptræning",
                    start_dato=datetime.now().date(),
                    forfald_dato=datetime.now().date() + timedelta(days=7),
                    beskrivelse=f"Opgave oprettet på vegne af: {leverandørnavn}",
                )

        opgave = self.nexus.hent_fra_reference(opgave_reference)
        self.nexus.opgaver.luk_opgave(opgave=opgave)
        self.tracker.track_task("Afslutning af borgere i genoptræning")
