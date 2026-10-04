#!/usr/bin/env python3
"""Synthetic receipts/LKG on REAL canonical private paths for Uninstall fixtures.

No candidate or service executes here. Ownership, generation/gate validation,
streamed inventories, retention normalization and Uninstall are production code.
"""
import importlib.util
import os
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('update_state_safety',ROOT/'lib/safety.py')
s=importlib.util.module_from_spec(spec); sys.modules[spec.name]=s; spec.loader.exec_module(s)
sys.path.insert(0,str(ROOT/'tests'))
from update_transactions import frozen

command,prefix=sys.argv[1:]; layout=s.UpdateLayout(Path(prefix))
assert os.geteuid()==0
if command=='baseline':
    # Generation cases use the actual digest-verified baseline ELF; no embedded
    # production hash or receipt validator is replaced in this fixture.
    s.update_install_baseline(layout)
    s.update_service_gate(layout)
elif command=='create':
    receipt=s.UpdateReceipt.create(layout.binary,uuid.uuid4().hex,uuid.uuid4().hex,frozen=frozen('3.5.12'))
    s.update_write_json(layout.receipt,receipt)
    s.update_write_json(layout.generation,s.update_generation_value(receipt))
    s.update_write_json(layout.data/'.telemt-web-manager-generation.json',dict(schema=1,generation_id=receipt['generation_id']))
    transaction=uuid.uuid4().hex
    for path in (layout.backups,layout.backup(transaction),layout.stash,layout.trees(transaction)):
        s.update_private_directory(path)
    old_binary=layout.backup(transaction)/'old-binary'; s.update_write(old_binary,b'inert old fixture binary')
    old=s.UpdateReceipt.create(old_binary,transaction,uuid.uuid4().hex,frozen=frozen('3.5.11'))
    account=s.fresh_identity(str(layout.data)); tree=s.UpdateTree(int(account['user'][2]),int(account['user'][3]))
    retained=layout.trees(transaction)/'old'
    tree.clone(layout.data,retained,tree.inventory(layout.data))
    s.update_write_json(retained/'.telemt-web-manager-generation.json',dict(schema=1,generation_id=old['generation_id']))
    index=tree.inventory(retained)
    s.update_write_json(layout.backup(transaction)/'stopped-data-index.json',index)
    s.update_write_json(layout.backup(transaction)/'old-receipt.json',old)
    journal=s.UpdateJournal(layout); journal.begin(old)
    journal.value.update(transaction_id=transaction,new=dict(receipt=receipt,receipt_present=True),
        snapshot=dict(sha256=s.update_hash(layout.backup(transaction)/'stopped-data-index.json')['sha256'],
                      entries=len(index['entries']),logical_bytes=index['logical_bytes'],generation_id=old['generation_id']))
    journal.value.update(phase='PREPARED'); journal.publish()
    journal.value.update(phase='COMMITTING'); journal.publish(); journal.intent('COMMIT'); journal.result('COMMITTED')
    s.update_gate_publish(layout)
    engine=s.UpdateEngine(layout); engine.journal=journal; engine.finish_committed()
    s.update_service_gate(layout)
    assert all(p.lstat().st_uid==p.lstat().st_gid==0 for p in [retained,*retained.rglob('*')])
    s.update_write_json(Path(prefix)/'retained-proof.json',tree.inventory(retained))
    s.update_write_json(Path(prefix)/'retained-transaction.json',dict(id=transaction))
elif command=='contract':
    s.update_gate_contract(layout); s.update_pending(layout); s.update_generation(layout)
elif command=='retained':
    transaction=s.update_json(s.update_read(Path(prefix)/'retained-transaction.json'))['id']
    account=dict(user=['telemt','x','424242','424242','',str(layout.data),'/usr/sbin/nologin'],group=['telemt','x','424242',''])
    assert s.UpdateTree(424242,424242).inventory(layout.trees(transaction)/'old')==s.update_json(s.update_read(Path(prefix)/'retained-proof.json'))
    s.uninstall_account_files(account,[layout.config.parent,layout.data])
else: raise ValueError('unknown fixture operation')
