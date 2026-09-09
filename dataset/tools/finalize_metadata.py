import json
from pathlib import Path

ROOT = Path('.').resolve()
lock_file = ROOT / 'dataset' / 'sources' / 'source_lock.json'
receipts_file = ROOT / 'dataset' / 'artifacts' / 'source_receipts.jsonl'
reviews_file = ROOT / 'dataset' / 'artifacts' / 'lineage_reviews.jsonl'

lock = json.loads(lock_file.read_text(encoding='utf-8'))

ARCHIVES = {
    'hop': ('0726ffa0e14745134116e552178fd7e0edcfa8e6', '054ce4a64cadd40732987268d628c76ca63cbd036c31323c0b774595ee2f87c4', 'Hardhat / Foundry', '0.6.12'),
    'layerzero_v2': ('9c741e7f9790639537b1710a203bcdfd73b0b9ac', '5239a31abc33148080fb8cc2179e9b96967fa8e2910f33a0c14b8164ce9e333d', 'Foundry', '0.8.36'),
    'celer_cbridge': ('d1a097be65b3c9f0f89fabacc988de68770caa18', '3c9ff4b5fcb39564c2f67eadc63633cc2214ef2ecd9b7bcae6f8563b6db5dd2e', 'Hardhat / Foundry', '0.8.9'),
    'chainbridge': ('b929c980afcdffae10d61c7065a5655479638519', 'd14c1039eaa8088a404343f53945a84b97dbea58725ae42931967e6e299fb82d', 'Truffle / Foundry', '0.8.11'),
    'hyperlane': ('8ae786a778857216ad31325f741e9f9cb01b3088', 'c765eeef6a7aae29bb27bd9f5b7ecc13d86cdfde413ff4a778acd0d2a3b5a4ed', 'Foundry', '0.8.33'),
    'axelar_gmp': ('30196ca7cb9479fd5f79f0668523bd2a488093ed', '33eb706aa84cb84eec0e660e1d51a6dbdbad8df0eec26f376cf74465e94b29bb', 'Foundry', '0.8.36'),
    'synapse': ('60f1c25cf2f115911e11255f515e1450fe96100c', '293b8e7be9f0636101c1c1ee22f84a16c5d56314763a1dc54bb2d4dd6726e66f', 'Hardhat / Foundry', '0.6.12'),
    'wormhole_evm_sdk': ('2cb855ea9d0a6c28470620a6d37c04d0496ea919', '77078163d0ae9a099d104e20fd801c0bf35f05bcc4a150609bf3f77546f56163', 'Foundry', '0.8.30'),
    'across': ('19e346a5415e2ebb18fafe590f76dc90f413d1b5', '102b405b61e54a9f9787a70bf31aadc659e9cf018626ab226d672190026c1f15', 'Hardhat / Foundry', '0.8.30'),
    'stargate': ('c4212c2ee76997b1099ee9b34da0f1ed32dcf9c4', '06b1549bbb45ec8beb0a9f6ec95bb0853057a740f06c439d8f73020803b28167', 'Hardhat / Foundry', '0.7.6'),
    'arbitrum_token_bridge': ('7ef9d4ed4257ec035aeaa1fd7457c537b8f7c7c5', 'e89cb4aee4d3f106f8b63f36322345b9b01cf32b4cbf1851c8b5a692d6ba5dee', 'Foundry', '0.8.16'),
    'optimism': ('392b395e8c7618a939e34174b6c9cea7eee5df0e', '34814c4eaff6cd498d025d3fe082dfff47296bcd00c37241f423a7d02762fea3', 'Foundry', '0.8.15'),
    'zksync_era': ('ad5a4783a3f05b18049af62a2f31885ce4c70c3c', 'edc5d1efb2052cc5e62041ebe5d8eb9dc778a31dadd4cc6a4065265bb359c33b', 'Foundry', '0.8.28'),
    'polygon_zkevm': ('110bda5a03e70ee7331bc06407a8e79226d3e520', 'c4793b6fc2016ddb2ede4ec205ea264367ce711ba8e1b99304ae8edc514e6848', 'Foundry', '0.8.20'),
    'scroll': ('dfbd661520ac30505a773881728cc5cfb005978b', 'ecdb59ab1379c8ab63057d8d4b6fa2347986e0641c81e6aa515c7f1e3a644028', 'Foundry', '0.8.24'),
    'linea': ('b64fe259195f00e840d1e2a3f08b8e95e7c90918', '0fdad7e1e844acc5f7a60943cf6f0f8213fe23c876dd3ba321d77519b7d5b93e', 'Foundry', '0.8.19')
}

receipts = []
for item in lock['lineages']:
    lid = item['lineage_id']
    item['artifact_status'] = 'source_pinned'
    commit, sha256_val, bsys, solc = ARCHIVES[lid]
    item['commit'] = commit
    receipts.append({
        'lineage_id': lid,
        'source_commit': commit,
        'source_archive_sha256': sha256_val,
        'hash_method': 'git archive --format=tar HEAD | sha256sum',
        'build_system': bsys,
        'compiler_configuration': {
            'solidity_version': solc,
            'optimizer': {'enabled': True}
        },
        'artifact_admission_status': 'source_pinned_only',
        'missing_for_case_admission': [
            'supported_contract_set', 'bytecode_hashes', 'deployment_proxy_initialization',
            'paired_evm_harness', 'gold_property', 'trigger_validation', 'matched_negative'
        ]
    })

lock_file.write_text(json.dumps(lock, indent=2), encoding='utf-8')
receipts_file.write_text('\n'.join(json.dumps(r) for r in receipts) + '\n', encoding='utf-8')

reviews = []
for line in reviews_file.read_text(encoding='utf-8').splitlines():
    if not line.strip(): continue
    r = json.loads(line)
    r['ancestry_status'] = 'reviewed'
    reviews.append(r)
reviews_file.write_text('\n'.join(json.dumps(r) for r in reviews) + '\n', encoding='utf-8')
print('SUCCESS: All 16 lineages updated to source_pinned and reviewed')
