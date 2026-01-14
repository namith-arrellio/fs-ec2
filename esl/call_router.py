from gevent import monkey

monkey.patch_all()

import gevent
import greenswitch
import logging
import re

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# =============================================================================
# ROUTING DATA
# =============================================================================

STORES = {
    "store1.local": {
        "did_variants": ["7577828734", "17577828734", "+17577828734"],
        "gateway": "telnyx_store1",
        "caller_id": "+17577828734",
        "context": "store1",
        "extensions": ["1000", "1001"],
        "ring_group": ["1000", "1001"],
        "park_slots": [
            "700",
            "701",
            "702",
            "703",
            "704",
            "705",
            "706",
            "707",
            "708",
            "709",
        ],
    },
    "store2.local": {
        "did_variants": ["7372449688", "17372449688", "+17372449688"],
        "gateway": "telnyx_store2",
        "caller_id": "+17372449688",
        "context": "store2",
        "extensions": ["1000", "1001"],
        "ring_group": ["1000", "1001"],
        "park_slots": [
            "700",
            "701",
            "702",
            "703",
            "704",
            "705",
            "706",
            "707",
            "708",
            "709",
        ],
    },
}

# Build lookup maps
DID_TO_STORE = {}
CONTEXT_TO_STORE = {}
for domain, data in STORES.items():
    for did in data["did_variants"]:
        DID_TO_STORE[did] = domain
    CONTEXT_TO_STORE[data["context"]] = domain


def normalize_number(number):
    if not number:
        return ""
    return (
        number.replace("+1", "")
        .replace("+", "")
        .replace("-", "")
        .replace(" ", "")
        .lstrip("1")
    )


def get_store_by_did(called_number):
    normalized = normalize_number(called_number)
    for variant in [called_number, normalized, f"1{normalized}", f"+1{normalized}"]:
        if variant in DID_TO_STORE:
            return DID_TO_STORE[variant]
    return None


def is_park_slot(called):
    """Check if destination is a park slot (handles park+70x or just 70x)"""
    # Strip park+ prefix if present
    slot = re.sub(r"^park\+", "", called)
    # Check if it matches 70x pattern
    return bool(re.match(r"^70\d$", slot))


def get_park_slot_number(called):
    """Extract just the slot number (e.g., 701 from park+701)"""
    return re.sub(r"^park\+", "", called)


def find_store_for_call(session_data):
    """Determine which store this call belongs to from session variables"""
    # Try variable_domain_name
    domain = session_data.get("variable_domain_name", "")
    if domain in STORES:
        return domain, STORES[domain]

    # Try variable_sip_auth_realm (the domain user registered to)
    realm = session_data.get("variable_sip_auth_realm", "")
    if realm in STORES:
        return realm, STORES[realm]

    # Try variable_sip_from_host
    from_host = session_data.get("variable_sip_from_host", "")
    if from_host in STORES:
        return from_host, STORES[from_host]

    # Try user_context variable
    user_context = session_data.get("variable_user_context", "")
    if user_context in CONTEXT_TO_STORE:
        domain = CONTEXT_TO_STORE[user_context]
        return domain, STORES[domain]

    # Try Caller-Context (last resort)
    context = session_data.get("Caller-Context", "")
    if context in CONTEXT_TO_STORE:
        domain = CONTEXT_TO_STORE[context]
        return domain, STORES[domain]

    # Default to first store
    logger.warning("Could not determine store, using default")
    first_domain = list(STORES.keys())[0]
    return first_domain, STORES[first_domain]


class CallHandler:
    def __init__(self, session):
        self.session = session
        logger.info("🔌 New ESL connection")

    def run(self):
        try:
            self.handle_call()
        except Exception as e:
            logger.exception(f"Error: {e}")
        finally:
            self.session.stop()

    def handle_call(self):
        self.session.myevents()
        self.session.linger()

        called = self.session.session_data.get("Caller-Destination-Number", "")
        caller = self.session.session_data.get("Caller-Caller-ID-Number", "")
        context = self.session.session_data.get("Caller-Context", "")
        uuid = self.session.session_data.get("Unique-ID", "")

        logger.info(f"📞 {caller} → {called} | Context: {context} | UUID: {uuid[:8]}")

        # =================================================================
        # PARK SLOT - Check FIRST, handles both 70x and park+70x
        # =================================================================
        if is_park_slot(called):
            self.handle_park(called, caller, context)
            return

        # =================================================================
        # NORMAL ROUTING
        # =================================================================
        if context == "public":
            self.handle_inbound(called, caller)
        elif context in CONTEXT_TO_STORE:
            self.handle_internal(called, caller, context)
        else:
            logger.warning(f"Unknown context: {context}")
            self.session.hangup("CALL_REJECTED")

    def handle_park(self, called, caller, context):
        """Handle park slot - works from any context"""
        slot = get_park_slot_number(called)

        if context in CONTEXT_TO_STORE:
            store_domain = CONTEXT_TO_STORE[context]
            store = STORES[store_domain]
        else:
            store_domain, store = find_store_for_call(self.session.session_data)

        # Use store domain (store1.local) as lot name to match phone subscription
        lot_name = store_domain  # e.g., "store1.local"

        logger.info(f"🅿️ Park slot {slot} → lot {lot_name}")
        self.session.call_command("set", "fifo_music=local_stream://moh")
        self.session.call_command("valet_park", f"{lot_name} {slot}")

    def handle_inbound(self, called, caller):
        """Inbound PSTN call → ring group"""
        store_domain = get_store_by_did(called)

        if not store_domain:
            logger.warning(f"No store for DID: {called}")
            self.session.hangup("UNALLOCATED_NUMBER")
            return

        store = STORES[store_domain]
        logger.info(f"🏪 Inbound → {store_domain}")

        self.session.call_command("set", f"domain_name={store_domain}")
        self.session.call_command("set", "ringback=${us-ring}")
        self.session.call_command("set", "call_timeout=30")
        self.session.call_command("set", "hangup_after_bridge=true")
        self.session.call_command("set", "continue_on_fail=true")

        targets = ",".join([f"user/{ext}" for ext in store["ring_group"]])
        bridge_string = f"{{leg_timeout=30,ignore_early_media=true}}{targets}"

        logger.info(f"🔔 Ringing: {targets}")
        self.session.bridge(bridge_string)

        hangup_cause = self.session.session_data.get(
            "variable_originate_disposition", ""
        )
        if hangup_cause not in ["SUCCESS", "ORIGINATOR_CANCEL"]:
            logger.info(f"Bridge result: {hangup_cause}, sending to voicemail")
            self.session.call_command("answer")
            gevent.sleep(0.5)
            self.session.call_command(
                "voicemail", f"default {store_domain} {store['ring_group'][0]}"
            )

    def handle_internal(self, called, caller, context):
        """Internal call (extension or outbound)"""
        store_domain = CONTEXT_TO_STORE.get(context)
        if not store_domain:
            self.session.hangup("CALL_REJECTED")
            return

        store = STORES[store_domain]

        # Extension call
        if called in store["extensions"]:
            logger.info(f"📱 Extension call → {called}")
            self.session.call_command("set", "ringback=${us-ring}")
            self.session.call_command("set", "call_timeout=30")
            self.session.call_command("set", "hangup_after_bridge=true")
            self.session.bridge(f"user/{called}")
            return

        # Outbound call
        if len(called) >= 10:
            logger.info(f"📤 Outbound → {called}")
            self.session.call_command(
                "set", f"effective_caller_id_number={store['caller_id']}"
            )
            self.session.call_command("set", "hangup_after_bridge=true")

            dial_number = normalize_number(called)
            if len(dial_number) == 10:
                dial_number = f"+1{dial_number}"
            elif not dial_number.startswith("+"):
                dial_number = f"+{dial_number}"

            self.session.bridge(f"sofia/gateway/{store['gateway']}/{dial_number}")
            return

        logger.warning(f"Unknown destination: {called}")
        self.session.hangup("UNALLOCATED_NUMBER")


if __name__ == "__main__":
    logger.info("🚀 ESL Call Router starting on 0.0.0.0:5002...")

    server = greenswitch.OutboundESLServer(
        bind_address="0.0.0.0",
        bind_port=5002,
        application=CallHandler,
        max_connections=50,
    )

    server.listen()
