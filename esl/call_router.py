# MUST be at the very top, before any other imports
from gevent import monkey

monkey.patch_all()

import gevent
import greenswitch
from greenswitch.esl import OutboundSessionHasGoneAway
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# =============================================================================
# STORE CONFIGURATION
# =============================================================================

STORES = {
    "store1.local": {
        "did": "7577828734",  # Normalized DID (10 digits)
        "gateway": "telnyx_store1",
        "caller_id": "+17577828734",
        "context": "store1",
        "extensions": ["1000", "1001"],
        "ring_group": ["1000", "1001"],
    },
    "store2.local": {
        "did": "7372449688",
        "gateway": "telnyx_store2",
        "caller_id": "+17372449688",
        "context": "store2",
        "extensions": ["1000", "1001"],
        "ring_group": ["1000", "1001"],
    },
}

# Build lookup maps at startup
DID_TO_STORE = {store["did"]: domain for domain, store in STORES.items()}
CONTEXT_TO_STORE = {store["context"]: domain for domain, store in STORES.items()}


def normalize_number(number):
    """Strip +1, spaces, dashes to get 10-digit number"""
    if not number:
        return ""
    return (
        number.replace("+1", "")
        .replace("+", "")
        .replace("-", "")
        .replace(" ", "")
        .lstrip("1")
    )


def format_outbound_number(number):
    """Format number for outbound dialing via Telnyx"""
    normalized = normalize_number(number)
    if len(normalized) == 10:
        return f"+1{normalized}"
    return f"+{normalized}"


class CallHandler:
    """Handle all calls from FreeSWITCH via Outbound ESL"""

    def __init__(self, session):
        self.session = session
        logger.info("🔌 New ESL connection")

    def run(self):
        """Main entry point - called by greenswitch for each connection"""
        try:
            self.handle_call()
        except OutboundSessionHasGoneAway:
            logger.info("📴 Call ended or transferred")
        except Exception as e:
            logger.exception(f"Error handling call: {e}")
        finally:
            self.session.stop()

    def handle_call(self):
        """Route call based on context"""
        self.session.myevents()
        self.session.linger()

        # Get call info
        called = self.session.session_data.get("Caller-Destination-Number", "")
        caller = self.session.session_data.get("Caller-Caller-ID-Number", "")
        context = self.session.session_data.get("Caller-Context", "")
        uuid = self.session.session_data.get("Unique-ID", "")[:8]

        logger.info(f"📞 {caller} → {called} | Context: {context} | UUID: {uuid}")

        # Route based on context
        if context == "public":
            # Inbound from Telnyx SIP trunk
            self.handle_inbound(called, caller)
        elif context in CONTEXT_TO_STORE:
            # From a registered Yealink phone
            self.handle_internal(called, caller, context)
        else:
            logger.warning(f"Unknown context: {context}")
            self.session.hangup("CALL_REJECTED")

    # =========================================================================
    # INBOUND: Telnyx → Yealink phones
    # =========================================================================

    def handle_inbound(self, called, caller):
        """Route inbound PSTN call to store's ring group"""
        normalized_did = normalize_number(called)
        store_domain = DID_TO_STORE.get(normalized_did)

        if not store_domain:
            logger.warning(
                f"❌ No store for DID: {called} (normalized: {normalized_did})"
            )
            self.session.hangup("UNALLOCATED_NUMBER")
            return

        store = STORES[store_domain]
        logger.info(f"🏪 Inbound call → {store_domain}")

        # Set channel variables
        self.session.call_command("set", f"domain_name={store_domain}")
        self.session.call_command("set", "ringback=${us-ring}")
        self.session.call_command("set", "call_timeout=30")
        self.session.call_command("set", "hangup_after_bridge=true")
        self.session.call_command("set", "continue_on_fail=true")

        # Build ring group dial string
        targets = ",".join(
            [f"user/{ext}@{store_domain}" for ext in store["ring_group"]]
        )
        bridge_string = f"{{leg_timeout=30,ignore_early_media=true}}{targets}"

        logger.info(f"🔔 Ringing: {targets}")

        try:
            self.session.bridge(bridge_string)
        except OutboundSessionHasGoneAway:
            logger.info("📴 Call transferred during bridge")
            return

        # Check if bridge failed (no answer, busy, etc.)
        disposition = self.session.session_data.get(
            "variable_originate_disposition", ""
        )
        if disposition not in ["SUCCESS", "ORIGINATOR_CANCEL"]:
            logger.info(f"Bridge result: {disposition} → voicemail")
            self._send_to_voicemail(store_domain, store["ring_group"][0])

    def _send_to_voicemail(self, domain, extension):
        """Send caller to voicemail after failed bridge"""
        try:
            self.session.call_command("answer")
            gevent.sleep(0.5)
            self.session.call_command("voicemail", f"default {domain} {extension}")
        except OutboundSessionHasGoneAway:
            logger.info("📴 Caller hung up before voicemail")

    # =========================================================================
    # INTERNAL: Yealink phone → extension or PSTN
    # =========================================================================

    def handle_internal(self, called, caller, context):
        """Route call from registered phone (extension or outbound)"""
        store_domain = CONTEXT_TO_STORE[context]
        store = STORES[store_domain]

        # Check if calling another extension
        if called in store["extensions"]:
            self._bridge_to_extension(called, store_domain)
            return

        # Check if outbound call (10+ digits)
        if len(called) >= 10:
            self._bridge_outbound(called, store)
            return

        logger.warning(f"❓ Unknown destination: {called}")
        self.session.hangup("UNALLOCATED_NUMBER")

    def _bridge_to_extension(self, extension, domain):
        """Bridge to another extension in the same store"""
        logger.info(f"📱 Extension call → {extension}@{domain}")

        self.session.call_command("set", "ringback=${us-ring}")
        self.session.call_command("set", "call_timeout=30")
        self.session.call_command("set", "hangup_after_bridge=true")

        try:
            self.session.bridge(f"user/{extension}@{domain}")
        except OutboundSessionHasGoneAway:
            logger.info("📴 Call ended during bridge")

    def _bridge_outbound(self, called, store):
        """Bridge outbound call via Telnyx gateway"""
        dial_number = format_outbound_number(called)
        logger.info(f"📤 Outbound → {dial_number} via {store['gateway']}")

        self.session.call_command(
            "set", f"effective_caller_id_number={store['caller_id']}"
        )
        self.session.call_command("set", "hangup_after_bridge=true")

        try:
            self.session.bridge(f"sofia/gateway/{store['gateway']}/{dial_number}")
        except OutboundSessionHasGoneAway:
            logger.info("📴 Call ended during outbound bridge")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    logger.info("🚀 ESL Call Router starting on 0.0.0.0:5002...")
    logger.info(f"📋 Configured stores: {list(STORES.keys())}")
    logger.info(f"📋 DID mappings: {DID_TO_STORE}")

    server = greenswitch.OutboundESLServer(
        bind_address="0.0.0.0",
        bind_port=5002,
        application=CallHandler,
        max_connections=50,
    )

    server.listen()
