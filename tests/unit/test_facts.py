from services.memory.facts import FactMemory


def test_save_and_get_fact():
    memory = FactMemory()
    
    memory.save_fact("test_name", "Sandeep")
    assert memory.get_fact("test_name") == "Sandeep"
    
def test_update_fact():
    memory = FactMemory()
    
    memory.save_fact("test_name", "Sandeep")
    memory.save_fact("test_color", "blue")
    
    facts = memory.get_all_facts()
    
    assert facts["test_name"] == "Sandeep"
    assert facts["test_color"] == "blue"
    
def test_delete_fact():
    memory = FactMemory()
    
    memory.save_fact("test_name", "Sandeep")
    memory.delete_fact("test_name")
    
    assert memory.get_fact("test_name") is None