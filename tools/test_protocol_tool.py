"""Unit tests use synthetic metadata only, never real benchmark evidence."""
from __future__ import annotations
import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import protocol_tool as tool

def fixture(index: int = 0) -> dict:
    digest = hashlib.sha256(f'SYNTHETIC-UNIT-TEST-{index}'.encode()).hexdigest()
    return {'instance_id':f'unit-test-{index}', 'lineage_id':f'test-lineage-{index}',
        'protocol_name':'SYNTHETIC_NOT_A_BRIDGE', 'version_id':'test',
        'split':'evaluation','cohort':'sealed','status':'vulnerable',
        'source_repository':'https://example.invalid/unit-test',
        'source_commit':'a'*40, 'source_sha256':digest,
        'artifact_pack_sha256':digest, 'compiler_settings_hash':digest,
        'chain_pair':['test-source','test-destination'],'architecture':'synthetic',
        'threat_profile_id':'test','attestation_profile_id':'test',
        'property_family':'replay','gold_property_id':'opaque-test',
        'ground_truth_evidence_hash':digest,'trigger_validation_status':'pass',
        'native_evm_scope':True,'seal_timestamp':'2026-09-07T00:00:00Z'}

class ManifestChecks(unittest.TestCase):
    def test_valid_basic_shape(self):
        errors,warnings=tool.validate([fixture(i) for i in range(12)])
        self.assertEqual(errors,[])
        self.assertEqual(warnings,[])
    def test_placeholder_hash_rejected(self):
        row=fixture();row['source_sha256']='ACTUAL_HASH'
        self.assertTrue(any('source_sha256' in e for e in tool.validate([row])[0]))
    def test_lineage_split_leakage(self):
        a,b=fixture(1),fixture(2);b['lineage_id']=a['lineage_id'];b['split']='development'
        self.assertTrue(any('leakage' in e for e in tool.validate([a,b])[0]))
    def test_gold_content_forbidden(self):
        row=fixture();row['gold_property']='SECRET_TEST'
        self.assertTrue(any('secret field' in e for e in tool.validate([row])[0]))
    def test_duplicate_id(self):
        row=fixture()
        self.assertTrue(any('duplicate instance_id' in e for e in tool.validate([row,copy.deepcopy(row)])[0]))
    def test_negative_requires_scope(self):
        row=fixture();row['cohort']='negative';row['status']='patched'
        self.assertTrue(any('validation scope' in e for e in tool.validate([row])[0]))
    def test_trigger_required(self):
        row=fixture();row['trigger_validation_status']='not_validated'
        self.assertTrue(any('validated trigger' in e for e in tool.validate([row])[0]))
    def test_missing_pair(self):
        row=fixture();row['paired_instance_id']='absent'
        self.assertTrue(any('absent' in e for e in tool.validate([row])[0]))

    def test_pair_linkage_must_be_reciprocal(self):
        a,b=fixture(1),fixture(2);a['paired_instance_id']=b['instance_id']
        b['lineage_id']=a['lineage_id']
        self.assertTrue(any('reciprocal' in e for e in tool.validate([a,b])[0]))

    def test_evaluation_mode_rejects_duplicate_artifact_content(self):
        a,b=fixture(1),fixture(2);a['paired_instance_id']=b['instance_id'];b['paired_instance_id']=a['instance_id']
        b['artifact_pack_sha256']=a['artifact_pack_sha256']
        self.assertTrue(any('duplicate artifact content' in e for e in tool.validate([a,b], 'evaluation')[0]))

    def test_placeholder_value_rejected(self):
        row=fixture();row['architecture']='replace'
        self.assertTrue(any('placeholder value' in e for e in tool.validate([row])[0]))
    def test_inventory_does_not_call_dependencies_unique(self):
        row=fixture();row['infrastructure_contract_count']=4
        counts=tool.inventory([row])
        self.assertEqual(counts['dependency_references_sum_not_unique_contracts'],4)
        self.assertEqual(counts['lineages'],1)

if __name__=='__main__':
    unittest.main()
