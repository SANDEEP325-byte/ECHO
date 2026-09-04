from services.brain.intent_router import Intent, intent_router

def test_intent_router_detects_time():
    assert intent_router.classify(
    "What time is it?"
    ) == Intent.TIME

def test_intent_router_detects_current_time():
    assert intent_router.classify(
    "What is the current time?"
    ) == Intent.TIME

def test_intent_router_detects_date():
    assert intent_router.classify(
    "What is today's date?"
    ) == Intent.DATE

def test_intent_router_detects_date_today():
    assert intent_router.classify(
    "What is the date today?"
    ) == Intent.DATE

def test_intent_router_detects_greeting():
    assert intent_router.classify(
    "Hello"
    ) == Intent.GREETING

def test_intent_router_detects_greeting_with_echo():
    assert intent_router.classify(
    "Hi ECHO"
    ) == Intent.GREETING

def test_intent_router_detects_identity():
    assert intent_router.classify(
    "Who are you?"
    ) == Intent.IDENTITY

def test_intent_router_detects_identity_by_name():
    assert intent_router.classify(
    "What's your name?"
    ) == Intent.IDENTITY

def test_intent_router_detects_memory_save_name():
    assert intent_router.classify(
    "My name is Sandeep"
    ) == Intent.MEMORY_SAVE

def test_intent_router_detects_memory_save_call_me():
    assert intent_router.classify(
    "Call me Sam"
    ) == Intent.MEMORY_SAVE

def test_intent_router_detects_memory_save_favorite_color():
    assert intent_router.classify(
    "My favorite color is blue"
    ) == Intent.MEMORY_SAVE

def test_intent_router_detects_memory_recall_name():
    assert intent_router.classify(
    "What is my name?"
    ) == Intent.MEMORY_RECALL

def test_intent_router_detects_memory_recall_general():
    assert intent_router.classify(
    "What do you remember about me?"
    ) == Intent.MEMORY_RECALL

def test_intent_router_detects_memory_delete_name():
    assert intent_router.classify(
    "Forget my name"
    ) == Intent.MEMORY_DELETE

def test_intent_router_detects_memory_delete_everything():
    assert intent_router.classify(
    "Forget everything"
    ) == Intent.MEMORY_DELETE

def test_intent_router_detects_calculator():
    assert intent_router.classify(
    "25 * 4"
    ) == Intent.CALCULATOR

def test_intent_router_detects_calculator_question():
    assert intent_router.classify(
    "What is 25 * 4?"
    ) == Intent.CALCULATOR

def test_intent_router_falls_back_to_general():
    assert intent_router.classify(
    "Tell me a joke"
    ) == Intent.GENERAL

def test_intent_router_normalizes_case():
    assert intent_router.classify(
    "WHAT TIME IS IT?"
    ) == Intent.TIME

def test_intent_router_normalizes_extra_spaces():
    assert intent_router.classify(
    "   What   time   is   it?   "
    ) == Intent.TIME
