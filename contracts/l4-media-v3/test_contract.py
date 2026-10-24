"""Portable shared descriptor checks; not live codec/decoder acceptance."""
import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parent
SCHEMA = json.loads((ROOT / 'media.schema.json').read_text())
VALIDATOR = Draft202012Validator(dict(SCHEMA, oneOf=[{'$ref':'#/$defs/descriptor'}]), format_checker=FormatChecker())

def descriptor(width=3000, height=2000, source='desktop', profile='low'):
    return dict(contract_version=3, descriptor_revision='12345678-1234-4234-8234-123456789abc',
        source_type=source, source_id='source-1', geometry_generation=1, profile_id=profile,
        tracks=[dict(track_id='video-main', kind='video', direction='producer_to_viewers',
            bit_depth=8, chroma='420', clock_rate=90000, payload_type=96, width=width,height=height,
            fps=15,feedback=dict(pli=True,fir=False),max_b_frames=0,keyframe_interval_ms=2000,
            repeat_parameter_sets=True,codec='h265',codec_profile='main',packetization='rfc7798',
            profile_space=0,profile_id=1,tier_flag=0,level_id=150,sprop_max_don_diff=0)])

class ContractTests(unittest.TestCase):
    def test_schema(self):
        Draft202012Validator.check_schema(SCHEMA)
    def test_native_sizes_for_both_profiles_and_sources(self):
        for size in [(800,600),(1024,768),(1280,1024),(1920,1080),(2048,1536),(3000,2000),(1080,1920)]:
            for source in ['desktop','usb-camera','camera']:
                for profile in ['low','default']:
                    with self.subTest(size=size,source=source,profile=profile):
                        VALIDATOR.validate(descriptor(*size,source,profile))
    def test_version_is_explicit(self):
        value=descriptor();del value['contract_version']
        self.assertFalse(VALIDATOR.is_valid(value))
        value['contract_version']=2
        self.assertFalse(VALIDATOR.is_valid(value))
    def test_quality_is_not_a_resolution_or_fps_limit(self):
        value=descriptor();value['tracks'][0]['fps']=30
        VALIDATOR.validate(value)
    def test_invalid_shape_and_codec_stay_rejected(self):
        for key,bad in [('width',0),('width',16386),('height',2001),('fps',0),('fps',121),
                        ('level_id',151),('tier_flag',1),('max_b_frames',1),('codec','av1')]:
            value=descriptor();value['tracks'][0][key]=bad
            with self.subTest(key=key,bad=bad):self.assertFalse(VALIDATOR.is_valid(value))
        value=descriptor();value['unknown_option']=True
        self.assertFalse(VALIDATOR.is_valid(value))
    def test_source_uses_identical_media_fields(self):
        a=descriptor();b=copy.deepcopy(a);b['source_type']='camera'
        VALIDATOR.validate(a);VALIDATOR.validate(b)
        self.assertEqual(a['tracks'],b['tracks'])

if __name__=='__main__':
    unittest.main()
