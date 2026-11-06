import pytest
from research.beta_v2.daily_entry import numeric_masses

def test_roundoff_only():
 assert numeric_masses([1+2.5e-13,0,0])==[1,0,0]
 assert numeric_masses([.5,-2e-13,.5])==[.5,0,.5]
 assert numeric_masses([0,1,0])==[0,1,0]
@pytest.mark.parametrize('p',[[1.01,0,0],[.8,0,.1],[.5,-.01,.51],[float('nan'),0,1]])
def test_material_invalid_rejected(p):
 with pytest.raises(ValueError):numeric_masses(p)
