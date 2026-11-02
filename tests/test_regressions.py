from datetime import date
from types import SimpleNamespace
import subprocess
import sys
from emporio import tools

def test_future_estimate_does_not_establish_receipt():
    p=SimpleNamespace(status='delivered', data=date(2026,2,1), previsao_entrega=date(2026,2,25))
    j=tools._janelas(p,date(2026,2,20))
    assert j['dias_desde_compra']==19
    assert j['dentro_prazo_arrependimento_7_dias'] is None
    assert j['dentro_garantia_legal_90_dias'] is None

def test_future_purchase_is_not_eligible():
    p=SimpleNamespace(status='delivered',data=date(2026,3,1))
    assert not tools._janelas(p,date(2026,2,20))['dentro_prazo_troca_defeito_30_dias']

def test_handoff_is_explicit_simulation(ctx):
    result=tools.encaminhar_para_atendente(ctx,'duvida','Teste')
    assert result['simulacao'] is True
    assert 'retorno' not in result

def test_dotenv_loaded_before_configuration():
    code='''
import os
from unittest.mock import patch
with patch('dotenv.load_dotenv', side_effect=lambda *a, **k: os.environ.update(EMPORIO_MODEL='modelo-teste')):
    from emporio import config
    assert config.MODEL == 'modelo-teste'
'''
    subprocess.run([sys.executable,'-c',code],env={**__import__('os').environ,'PYTHONPATH':'src'},check=True)
