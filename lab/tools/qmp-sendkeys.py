"""Agent lab tool: type into the KVM guest via authenticated QMP. --secret reads a file and never echoes it.

Usage: [DESKTOPFORGE_VM_PROFILE=kvm|sddm] qmp-sendkeys.py (--secret FILE | --text TEXT | --key QCODE...)
"""
import importlib.machinery, importlib.util, sys, time
loader = importlib.machinery.SourceFileLoader('dfvm', str(__import__('pathlib').Path(__file__).resolve().parents[2] / 'scripts/desktopforge-vm'))
spec = importlib.util.spec_from_loader('dfvm', loader); m = importlib.util.module_from_spec(spec); loader.exec_module(m)
import os
m.select_profile(os.environ.get('DESKTOPFORGE_VM_PROFILE', 'kvm'))  # which VM receives the keys
SHIFTED = {'!':'1','@':'2','#':'3','$':'4','%':'5','^':'6','&':'7','*':'8','(':'9',')':'0','_':'minus','+':'equal',
           '{':'bracket_left','}':'bracket_right','|':'backslash',':':'semicolon','"':'apostrophe','<':'comma','>':'dot','?':'slash','~':'grave_accent'}
PLAIN = {'-':'minus','=':'equal','[':'bracket_left',']':'bracket_right','\\':'backslash',';':'semicolon',"'":'apostrophe',
         ',':'comma','.':'dot','/':'slash','`':'grave_accent',' ':'spc'}
def keys_for(c):
    if c.isalpha() and c.isascii(): return (['shift'] if c.isupper() else []) + [c.lower()]
    if c.isdigit(): return [c]
    if c in PLAIN: return [PLAIN[c]]
    if c in SHIFTED: return ['shift', SHIFTED[c]]
    raise SystemExit('unsupported character in input')
def press(codes):
    m.qmp('send-key', {'keys': [{'type': 'qcode', 'data': k} for k in codes], 'hold-time': 40}); time.sleep(0.06)
mode, rest = sys.argv[1], sys.argv[2:]
if mode == '--secret':
    text = open(rest[0]).read().rstrip('\n')
    for c in text: press(keys_for(c))
    print(f'typed {len(text)} secret characters')
elif mode == '--text':
    for c in rest[0]: press(keys_for(c))
else:
    for combo in rest: press(combo.split('-'))
