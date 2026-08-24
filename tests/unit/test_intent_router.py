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