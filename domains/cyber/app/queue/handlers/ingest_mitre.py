"""Handler: MITRE CWE + CAPEC + ATT&CK ingest (all three in dependency order)."""

import logging

logger = logging.getLogger(__name__)


async def handle_ingest_mitre(task: dict) -> dict:
    """Run all MITRE ingests: CWE → CAPEC → ATT&CK (dependency order)."""
    logger.info("Running MITRE ingest via task queue (CWE → CAPEC → ATT&CK)")

    from domains.cyber.app.ingest.mitre_cwe import ingest_cwe
    from domains.cyber.app.ingest.mitre_capec import ingest_capec
    from domains.cyber.app.ingest.mitre_attack import ingest_attack

    cwe_result = await ingest_cwe()
    capec_result = await ingest_capec()
    attack_result = await ingest_attack()

    return {"cwe": cwe_result, "capec": capec_result, "attack": attack_result}
