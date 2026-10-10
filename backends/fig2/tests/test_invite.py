import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import client as c
import invite

class InviteTests(unittest.TestCase):
    def test_required_and_encrypted_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'order'
            class API:
                def me(self):return dict(id='customer',credits_available=0,credits_per_task=45,invite_required=True)
                def submit(self,payload):
                    self.payload=payload
                    return dict(job_id='fgp_'+'a'*24,charged_credits=45,status='queued')
            api=API()
            args=dict(image=None,text='Cell',application='ppt',thread_id='11111111-1111-1111-1111-111111111111',credential_file=Path(tmp)/'key',credits_approved=45,wake_authorized=True,api=api,registry=Path(tmp)/'registry')
            with self.assertRaises(c.ClientError):c.prepare(directory,**args)
            self.assertFalse((directory/'job.json').exists())
            permit='Cell_Projkldjd'
            with patch.object(invite,'transform',side_effect=lambda b,protect:bytes(v^42 for v in b)):
                state=c.prepare(directory,**args,invite_code=permit)
                self.assertNotIn(permit,(directory/'job.json').read_text())
                self.assertNotIn('invite_ciphertext',c.public(state))
                c.submit_existing(directory,api)
                self.assertEqual(api.payload['invite_code'],permit)
                self.assertEqual(api.payload['request_id'],state['request_id'])

    def test_invalid_invite_rejected_before_encryption(self):
        with patch.object(invite,'transform') as transform:
            for value in (None,'','img_live_'+'a'*40,'fgp_inv_short'):
                with self.assertRaises(ValueError):invite.encrypt(value)
            transform.assert_not_called()
        self.assertIsNone(invite.decrypt({}))

if __name__=='__main__':unittest.main()
