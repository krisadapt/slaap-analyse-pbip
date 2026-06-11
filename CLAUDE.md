# CLAUDE.md — PBIP Slaapanalyse-rapport

## Project
Slaapanalyse-dashboard: Power BI-rapport met 3 pagina's (Overzicht, Nacht-detail, Gedragstags).

## Workspace
- **Root:** `E:\ADAPT\04 Projecten - Documents\18 CPAP Analyse\Rapporten\PBIP\`
- **Vault:** `E:\Documentatie\Second Brain\00 Projects\Someday Maybe Projects\CPAP analyse\`
- **Fileserver:** `E:\ADAPT\04 Projecten - Documents\18 CPAP Analyse\`
- **GitHub:** `https://github.com/krisadapt/slaap-analyse-pbip` (private)

## Model
- **Tabellen:** Slaapdata (G), OSCAR Daily/Events/Details, Gedrag, Kalender, OSCAR Events (ref), Metingen
- **Measures:** 25 stuks (AHI, Garmin-metingen, Vergelijking)
- **Relaties:** Gedrag.Nacht → Kalender; Details.Nacht → Kalender; datumcorrectie OSCAR +1
- **Compatibility:** 1601 (dynamic format strings)

## Visueel (in voortgang)
- **Pagina 1:** KPI's + 4 charts (AHI-trend, slaapduur vs masker, slaapfasen, herstel)
- **Pagina 2:** Nacht-detail (KPI's, kwartier-events per Eventgroep, vergelijking)
- **Pagina 3:** Gedragstags (heatmap datum × categorie, frequentie)

## Knelpunten
- Card visual: compact maken (padding/font)
- Heatmap: matrix-visual opzet (datum × categorie, kleur naar aantal)

## Volgende sessie
1. Git: `git push` naar GitHub (PBIP-repo linken)
2. Visueel: card + heatmap afmaken op basis van screenshots
3. Model: measures-aanpassingen naar visueel-feedback
4. Documenten: afronden (plan, rapportbeschrijving)
5. Fase 3 voorbereiding: Gedrag-factor-mapping

## Commando's
```bash
cd "E:\ADAPT\04 Projecten - Documents\18 CPAP Analyse\Rapporten\PBIP"
git status
git push origin main
```

---

**Status:** Model ✅ | Visueel 🔄 | GitHub-push ⏳
**Last updated:** 2026-06-10 23:00 UTC
