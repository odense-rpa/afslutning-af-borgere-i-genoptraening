from datetime import datetime, timedelta
from kmd_nexus_client import NexusClientManager
from kmd_nexus_client.functionality.tilstande import Tilstandsgruppe
from kmd_nexus_client.tree_helpers import filter_by_path
from odk_tools.reporting import report
from odk_tools.tracking import Tracker


class NexusService:
    def __init__(
        self,
        nexus: NexusClientManager,
        tracker: Tracker,
    ):
        self.nexus = nexus
        self.tracker = tracker


    def _afslut_indsats(self, borger: dict, indsats_reference: dict):
        indsats = self.nexus.hent_fra_reference(indsats_reference)
        
        if indsats.get("workflowState", {}).get("name") in [
            "Afsluttet",
            "Annulleret",
            "Fjernet",
            "Frafaldet",
            "Afgjort",
            "Afslået",
            "Ophørt"
        ]:
            return
        
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
            report(
                report_id="afslutning_af_borgere_i_genoptraening",
                group="Fejl",
                json={
                    "Cpr": borger["patientIdentifier"]["identifier"],
                    "Fejl": "Kunne ikke afslutte indsats med navn: " + indsats.get("name", "Uden navn"),
                },
            )


    def afslut_indsatser(self, borger: dict):
        pathway = self.nexus.borgere.hent_visning(borger=borger)
        referencer = self.nexus.borgere.hent_referencer(visning=pathway)        
        indsatser_referencer = filter_by_path(
            referencer,
            path_pattern="/Ældre og sundhedsfagligt grundforløb/Sag SOFF: Genoptræning og fysioterapi efter sundhedsloven/Indsatser/basketGrantReference",
            active_pathways_only=True,
        )

        for indsats_reference in indsatser_referencer:
            self._afslut_indsats(borger, indsats_reference)

        

    def afslut_skemaer(self, borger: dict):
        pathway = self.nexus.borgere.hent_visning(borger=borger)

        if pathway is None:
            raise ValueError(
                f"Kunne ikke finde -Alt for borger {borger['patientIdentifier']['identifier']}"
            )

        referencer = self.nexus.borgere.hent_referencer(visning=pathway)

        filtrerede_skema_referencer = filter_by_path(
            referencer,
            path_pattern="/Ældre og sundhedsfagligt grundforløb/Sag SOFF: Genoptræning og fysioterapi efter sundhedsloven/formDataV2Reference",
            active_pathways_only=True,
        )

        aktive_skemaer = [
            skema_ref
            for skema_ref in filtrerede_skema_referencer
            if skema_ref.get("formDataStatus") == "Aktivt"
        ]

        for skema_reference in aktive_skemaer:
            skema = self.nexus.hent_fra_reference(skema_reference)

            relationer = self.nexus.nexus_client.get(
                skema["_links"]["relatedActivities"]["href"]
            ).json()

            for relation in relationer:
                for aktivitet in relation.get("citizenActivitiesGroups", []):
                    for aktivitet_item in aktivitet.get("activities", []):
                        try:
                            self.nexus.nexus_client.delete(aktivitet_item["_links"]["deleteActivityLink"]["href"])
                        except Exception:
                            continue
                

            # Sæt skema til inaktivt
            self.nexus.skemaer.rediger_skema(skema, "Inaktivt", data={})


    def kontroller_udenbys_borger(self, borger: dict, opgave_skema: dict) -> bool:
        pathway = self.nexus.borgere.hent_visning(borger=borger)

        if pathway is None:
            raise ValueError(
                f"Kunne ikke finde -Alt for borger {borger['patientIdentifier']['identifier']}"
            )

        referencer = self.nexus.borgere.hent_referencer(visning=pathway)

        filtrerede_indsats_referencer = filter_by_path(
            referencer,
            path_pattern="/Ældre og sundhedsfagligt grundforløb/*/Indsatser/Genoptræning udenbys borger (SUL § 140)",
            active_pathways_only=True,
        )

        filtrerede_indsats_referencer = [
            indsats
            for indsats in filtrerede_indsats_referencer
            if indsats.get("workflowState", {}).get("name") not in [
                "Afsluttet",
                "Annulleret",
                "Fjernet",
                "Frafaldet",
                "Afgjort",
                "Afslået",
                "Ophørt"
            ]
        ]

        if len(filtrerede_indsats_referencer) > 0:
            self.nexus.opgaver.opret_opgave(
                objekt=opgave_skema,
                opgave_type="Afslut genoptræningsforløb SUL § 140 - besked fra robot",
                titel="Udenbys borger",
                ansvarlig_organisation="Myndighed genoptræning",
                start_dato=datetime.now().date(),
                forfald_dato=datetime.now().date(),
                beskrivelse="Robotten kan ikke afslutte borgers genoptræningsforløb, da borgeren er udenbys.",
            )
            return True

        return False
    

    def kontroller_aktive_hjælpemidler(self, borger: dict, leverandørnavn: str):
        # Check hjælpemidler
        hjaelpemiddelsindsatser = [
            "SEL § 86 Træning Hjælpemidler",
            "SUL § 140 Træning Hjælpemidler",
            "ÆL § 9 Træning Hjælpemidler",
        ]

        aktive_udlån = self.nexus.borgere.hent_udlån(borger=borger)

        if aktive_udlån is not None and len(aktive_udlån) > 0:
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



    def afslut_forløb(self, borger: dict) -> bool:
        pathway = self.nexus.borgere.hent_visning(borger=borger)
        referencer = self.nexus.borgere.hent_referencer(visning=pathway)
        forløbs_referencer = filter_by_path(
            referencer,
            path_pattern="/Ældre og sundhedsfagligt grundforløb/Sag SOFF: Genoptræning og fysioterapi efter sundhedsloven",
            active_pathways_only=True,
        )

        forløb = self.nexus.hent_fra_reference(forløbs_referencer[0])
        try:
            self.nexus.forløb.luk_forløb(forløb_reference=forløb)
        except Exception:
            report(
                report_id="afslutning_af_borgere_i_genoptraening",
                group="Fejl",
                json={
                    "Cpr": borger["patientIdentifier"]["identifier"],
                    "Fejl": "Kunne ikke afslutte forløb",
                },
            )
            return False
        return True


    def afslut_forløbsindplacering(self, borger: dict):
        FORLØBS_BEGRÆNSNINGER = [
            "Sag SOFF: Helhedspleje",
            "Sag SOFF: Pleje, omsorg og træning",
            "Sag SOFF: Sygepleje",
            "Sag SOFF: Dagcenter",
            "Sag SOFF: Kommunal tandpleje",
            "Sag SOFF: Social service. Plejebolig og Ældrebolig"
        ]
        pathway = self.nexus.borgere.hent_visning(borger=borger)
        referencer = self.nexus.borgere.hent_referencer(visning=pathway)

        for forløbsbegrænsning in FORLØBS_BEGRÆNSNINGER:
            forløbs_referencer = filter_by_path(
                referencer,
                path_pattern=f"/Ældre og sundhedsfagligt grundforløb/{forløbsbegrænsning}",
                active_pathways_only=True,
            )
            if len(forløbs_referencer) > 0:
                # Returner hvis borger har én af disse aktive forløb, da der ikke er belæg for afslutning af forløbsindplacering
                return
        
        filtrerede_indsats_referencer = filter_by_path(
            referencer,
            path_pattern="/ÆHF - Forløbsindplacering (Grundforløb)/Forløbsindplacering/Indsatser/*",
            active_pathways_only=True,
        )

        for indsats_reference in filtrerede_indsats_referencer:
            self._afslut_indsats(borger=borger, indsats_reference=indsats_reference)

    def fjern_medarbejdere(self, borger: dict):
        pathway = self.nexus.borgere.hent_visning(borger=borger)
        referencer = self.nexus.borgere.hent_referencer(visning=pathway)
        medarbejder_referencer = filter_by_path(
            referencer,
            path_pattern="/Ældre og sundhedsfagligt grundforløb/Sag SOFF: Genoptræning og fysioterapi efter sundhedsloven/professionalReference",
            active_pathways_only=True,
        )
        for medarbejder_reference in medarbejder_referencer:            
            self.nexus.organisationer.fjern_medarbejder_fra_forløb(
                medarbejder_reference=medarbejder_reference
            )


    def fjern_organisationstilknytning(self, borger: dict, leverandørnavn: str):
        relationer = self.nexus.organisationer.hent_organisationer_for_borger(
            borger=borger
        )
        for relation in relationer:
            if relation["organization"]["name"] == leverandørnavn:
                self.nexus.organisationer.fjern_borger_fra_organisation(
                    organisations_relation=relation
                )

    def fjern_relationer_og_inaktiver_tilstande(self, borger: dict):
        grupper = self.nexus.tilstande.hent_tilstandsgrupper(borger, Tilstandsgruppe.GENOPTRÆNING)
        
        for visitation in grupper.get("conditionGroupVisitation", []):
            for condition in visitation.get("conditions", []):
                if not condition.get("state") == "ACTIVE":
                    # Smider åbenbart HTTP 400, hvis man kalder på en inaktiv condition, som ikke har været aktiv før.
                    continue

                relaterede_aktiviteter = self.nexus.nexus_client.get(condition.get("_links", {}).get("relatedActivities", []).get("href", "")).json()
                for kategori in relaterede_aktiviteter:
                    if kategori.get("groupName") == "Indsatser":
                        for aktivitet in kategori.get("citizenActivitiesGroups", []):
                            for aktivitet_item in aktivitet.get("activities", []):
                                try:
                                    self.nexus.nexus_client.delete(aktivitet_item["_links"]["deleteActivityLink"]["href"])
                                except Exception:
                                    continue

        for visitation in grupper.get("conditionGroupVisitation", []):
            for condition in visitation.get("conditions", []):
                if condition.get("state") == "ACTIVE":
                    condition["state"] = "INACTIVE"

        self.nexus.tilstande.opdater_tilstandsgrupper(grupper)
                

    def er_der_flere_genoptræningsplaner(self, borger: dict, opgave_skema: dict, leverandørnavn: str) -> bool:
        pathway = self.nexus.borgere.hent_visning(borger=borger)
        referencer = self.nexus.borgere.hent_referencer(visning=pathway)

        henvisnings_skemaer = filter_by_path(
            referencer,
            path_pattern="/Ældre og sundhedsfagligt grundforløb/Sag SOFF: Genoptræning og fysioterapi efter sundhedsloven/formDataV2Reference",
            active_pathways_only=True,
        )
        
        henvisnings_skemaer = [
            skema_ref
            for skema_ref in henvisnings_skemaer
            if skema_ref.get("name")
            == "Henvisning - Genoptræning efter sundhedsloven med indberetning" and 
            skema_ref.get("formDataStatus") != "Slettet"
        ]

        if len(henvisnings_skemaer) > 1:
            self.nexus.opgaver.opret_opgave(
                objekt=opgave_skema,
                opgave_type="Afslut genoptræningsforløb SUL § 140 - besked fra robot",
                titel="Flere genoptræningsforløb",
                ansvarlig_organisation=leverandørnavn,
                start_dato=datetime.now().date(),
                forfald_dato=datetime.now().date(),
                beskrivelse="Robotten kan ikke afslutte borgers genoptræningsforløb, da der muligvis er flere igangværende genoptræningsforløb.",
            )
            return True

        henvisnings_skema = self.nexus.hent_fra_reference(henvisnings_skemaer[0])
        if (
            not henvisnings_skema.get("workflowState", {}).get("name")
            == "Udfyldt"
        ):
            try:
                self.nexus.skemaer.rediger_skema(
                    skema=henvisnings_skema, handling_navn="Udfyldt", data={}
                )
            except Exception:
                report(
                    report_id="afslutning_af_borgere_i_genoptraening",
                    group="Fejl",
                    json={
                        "Cpr": borger["patientIdentifier"]["identifier"],
                        "Fejl": "Kunne ikke redigere henvisningsskema med status Udfyldt",
                    },
                )
                return True

        return False
