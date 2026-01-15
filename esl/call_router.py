# MUST be at the very top, before any other imports
from gevent import monkey

monkey.patch_all()

import gevent
import greenswitch
import socket
import uuid as uuid_module
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

STORES = {
    "store1.local": {
        "did": "7577828734",
        "gateway": "telnyx_store1",
        "caller_id": "+17577828734",
        "context": "store1",
        "extensions": ["1000", "1001"],
        "ring_group": ["1000", "1001"],
        "park_slots": ["700", "701", "702"],
    },
    "store2.local": {
        "did": "7372449688",
        "gateway": "telnyx_store2",
        "caller_id": "+17372449688",
        "context": "store2",
        "extensions": ["1000", "1001"],
        "ring_group": ["1000", "1001"],
        "park_slots": ["700", "701", "702"],
    },
}

# Kamailio configuration for presence publishing
KAMAILIO_HOST = "127.0.0.1"
KAMAILIO_PORT = 5060

# FreeSWITCH ESL configuration (for Inbound ESL)
FREESWITCH_HOST = "127.0.0.1"
FREESWITCH_ESL_PORT = 8021
FREESWITCH_ESL_PASSWORD = "ClueCon"


# =============================================================================
# PRESENCE PUBLISHER (for Kamailio BLF)
# =============================================================================


class PresencePublisher:
    """Publishes SIP PUBLISH messages to Kamailio for BLF updates"""

    def __init__(self, kamailio_host, kamailio_port):
        self.kamailio_host = kamailio_host
        self.kamailio_port = kamailio_port
        self.local_ip = self._get_local_ip()
        self.cseq_counter = 1
        # Track parked calls: {domain: {slot: caller_info}}
        self.parked_calls = {}
        for domain, config in STORES.items():
            self.parked_calls[domain] = {slot: None for slot in config["park_slots"]}

    def _get_local_ip(self):
        """Get local IP address"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((self.kamailio_host, self.kamailio_port))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

    def publish_park_status(self, slot, domain, is_parked, caller_info=None):
        """Publish parking slot status to Kamailio"""
        entity = f"sip:{slot}@{domain}"
        state = "confirmed" if is_parked else "terminated"

        dialog_info = self._generate_dialog_info(
            entity, slot, domain, state, caller_info
        )
        self._send_publish(entity, domain, dialog_info)

        # Update local tracking
        if domain in self.parked_calls:
            self.parked_calls[domain][slot] = caller_info if is_parked else None

    def _generate_dialog_info(
        self, entity, local_user, domain, state, remote_info=None
    ):
        """Generate dialog-info+xml body"""
        dialog_id = str(uuid_module.uuid4())
        self.cseq_counter += 1

        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<dialog-info xmlns="urn:ietf:params:xml:ns:dialog-info" version="{self.cseq_counter}" state="full" entity="{entity}">
  <dialog id="{dialog_id}" direction="recipient">
    <state>{state}</state>
    <local>
      <identity display="{local_user}">{entity}</identity>
      <target uri="{entity}"/>
    </local>"""

        if remote_info:
            body += f"""
    <remote>
      <identity display="{remote_info}">sip:{remote_info}@{domain}</identity>
      <target uri="sip:{remote_info}@{domain}"/>
    </remote>"""

        body += """
  </dialog>
</dialog-info>"""

        return body

    def _send_publish(self, entity, domain, body):
        """Send a SIP PUBLISH request via UDP to Kamailio"""
        call_id = f"presence-{self.cseq_counter}-{uuid_module.uuid4().hex[:8]}@{self.local_ip}"

        request = f"""PUBLISH {entity} SIP/2.0\r
Via: SIP/2.0/UDP {self.local_ip}:5080;rport;branch=z9hG4bK{uuid_module.uuid4().hex[:16]}\r
Max-Forwards: 70\r
From: <{entity}>;tag={uuid_module.uuid4().hex[:8]}\r
To: <{entity}>\r
Call-ID: {call_id}\r
CSeq: {self.cseq_counter} PUBLISH\r
Contact: <sip:freeswitch@{self.local_ip}:5080>\r
Event: dialog\r
Expires: 3600\r
Content-Type: application/dialog-info+xml\r
Content-Length: {len(body)}\r
\r
{body}"""

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(request.encode(), (self.kamailio_host, self.kamailio_port))
            sock.settimeout(2)

            try:
                response, addr = sock.recvfrom(4096)
                logger.debug(f"PUBLISH response: {response.decode()[:100]}")
            except socket.timeout:
                logger.warning("No response to PUBLISH (timeout)")

            sock.close()
            logger.info(f"📡 Published presence for {entity}")
        except Exception as e:
            logger.error(f"Failed to send PUBLISH: {e}")


# Global presence publisher instance
presence_publisher = None


# =============================================================================
# INBOUND ESL EVENT HANDLER (for system-wide events)
# =============================================================================


def handle_esl_event(event):
    """Handle events from FreeSWITCH Inbound ESL"""
    global presence_publisher

    event_name = event.get("Event-Name")
    event_subclass = event.get("Event-Subclass")

    # Handle valet parking events
    if event_subclass and "valet_parking" in event_subclass:
        handle_park_event(event)

    # Handle channel events for extension BLF (optional)
    elif event_name in ["CHANNEL_ANSWER", "CHANNEL_HANGUP_COMPLETE"]:
        handle_channel_event(event)


def handle_park_event(event):
    """Handle valet parking events for BLF"""
    global presence_publisher

    if not presence_publisher:
        return

    action = event.get("Action")
    valet_lot = event.get("Valet-Lot-Name") or event.get("variable_valet_lot")
    valet_extension = event.get("Valet-Extension") or event.get(
        "variable_valet_extension"
    )
    caller_id = event.get("Caller-Caller-ID-Number", "Unknown")

    if not valet_lot or not valet_extension:
        logger.debug(f"Ignoring park event without lot/extension info")
        return

    # Determine domain from lot name
    domain = valet_lot if valet_lot in STORES else None
    if not domain:
        logger.warning(f"Unknown valet lot: {valet_lot}")
        return

    if action == "hold":
        logger.info(
            f"📦 Call PARKED in {domain} slot {valet_extension} (caller: {caller_id})"
        )
        presence_publisher.publish_park_status(valet_extension, domain, True, caller_id)
    elif action == "bridge":
        logger.info(f"📤 Call RETRIEVED from {domain} slot {valet_extension}")
        presence_publisher.publish_park_status(valet_extension, domain, False)


def handle_channel_event(event):
    """Handle channel events for extension presence (optional)"""
    # This can be extended to publish extension status to Kamailio
    pass


def run_inbound_esl():
    """Run Inbound ESL client to listen for system events"""
    global presence_publisher

    presence_publisher = PresencePublisher(KAMAILIO_HOST, KAMAILIO_PORT)
    logger.info(
        f"📡 Presence publisher initialized (Kamailio: {KAMAILIO_HOST}:{KAMAILIO_PORT})"
    )

    while True:
        try:
            logger.info(
                f"🔌 Connecting to FreeSWITCH ESL ({FREESWITCH_HOST}:{FREESWITCH_ESL_PORT})..."
            )

            # Create Inbound ESL connection
            inbound = greenswitch.InboundESL(
                host=FREESWITCH_HOST,
                port=FREESWITCH_ESL_PORT,
                password=FREESWITCH_ESL_PASSWORD,
            )

            # Register event handler before connecting
            def on_event(event):
                gevent.spawn(handle_esl_event, event)

            inbound.register_handle("*", on_event)
            inbound.connect()
            logger.info("✅ Connected to FreeSWITCH ESL")

            # Subscribe to events
            inbound.send("event plain CUSTOM valet_parking::info")
            inbound.send("event plain CHANNEL_ANSWER CHANNEL_HANGUP_COMPLETE")
            logger.info("📋 Subscribed to parking and channel events")

            # Keep the connection alive - greenswitch handles events via callbacks
            while inbound.connected:
                gevent.sleep(1)

            logger.warning("ESL connection lost")

        except Exception as e:
            logger.error(f"ESL connection error: {e}")
            logger.info("Reconnecting in 5 seconds...")
            gevent.sleep(5)


# =============================================================================
# OUTBOUND ESL CALL HANDLER (existing call routing logic)
# =============================================================================


def get_route_from_backend(called_number, caller_id):
    """Hardcoded routing logic - no database"""
    normalized = (
        called_number.replace("+1", "")
        .replace("-", "")
        .replace(" ", "")
        .replace("+", "")
    )

    for domain, config in STORES.items():
        if normalized == config["did"] or called_number == f"1{config['did']}":
            logger.info(f"Routing call to {domain}: {called_number}")
            return {
                "action": "bridge",
                "targets": [f"user/{ext}@{domain}" for ext in config["ring_group"]],
                "context": config["context"],
                "domain": domain,
            }

    return {"action": "reject", "reason": "No route found for " + called_number}


class InboundCallHandler(object):
    """Handle inbound calls from FreeSWITCH via Outbound ESL"""

    def __init__(self, session):
        self.session = session
        logger.info("🔌 New FreeSWITCH connection received!")

    def run(self):
        """Main function called when FreeSWITCH connects for a call"""
        try:
            self.handle_call()
        except:
            logger.exception("Exception raised when handling call")
            self.session.stop()

    def handle_call(self):
        """Process the inbound call"""
        # CRITICAL: Subscribe to events for this call
        self.session.myevents()
        logger.debug("myevents sent")

        # Keep receiving events even after hangup
        self.session.linger()
        logger.debug("linger sent")

        # Get call variables from session_data (populated by connect())
        called_number = self.session.session_data.get("Caller-Destination-Number")
        caller_id = self.session.session_data.get("Caller-Caller-ID-Number")
        uuid = self.session.session_data.get("Unique-ID")
        profile = self.session.session_data.get("variable_sip_profile_name", "")

        logger.info(f"📞 Inbound call: {caller_id} -> {called_number} (UUID: {uuid})")

        # Get routing decision
        route = get_route_from_backend(called_number, caller_id)
        logger.info(f"Routing decision: {route['action']}")

        if route["action"] == "bridge":
            # Set channel variables using call_command instead of setVariable
            self.session.call_command("set", f"domain_name={route['domain']}")
            self.session.call_command("set", "ringback=${us-ring}")
            self.session.call_command("set", "call_timeout=30")
            self.session.call_command("set", "hangup_after_bridge=true")
            self.session.call_command("set", "continue_on_fail=true")

            self.session.answer()
            logger.debug("answered")
            gevent.sleep(0.5)

            targets = ",".join(route["targets"])
            bridge_string = f"{{leg_timeout=30,ignore_early_media=true}}{targets}"
            logger.info(f"Bridging to: {targets}")

            self.session.bridge(bridge_string, block=False)
            logger.info("✓ Bridge command sent")

        elif route["action"] == "reject":
            logger.info(f"✗ Rejecting: {route.get('reason')}")
            self.session.hangup(route.get("reason", "CALL_REJECTED"))

        # Close the socket
        self.session.stop()


# =============================================================================
# MAIN - Run both Outbound ESL Server and Inbound ESL Client
# =============================================================================

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Starting ESL Service (Call Router + Presence Publisher)")
    logger.info("=" * 60)

    # Start Inbound ESL client for presence events (in background greenlet)
    logger.info("🚀 Starting Inbound ESL client for presence events...")
    gevent.spawn(run_inbound_esl)

    # Start Outbound ESL server for call routing (main greenlet)
    logger.info("🚀 Starting Outbound ESL server on 0.0.0.0:5002...")
    logger.info("Waiting for FreeSWITCH connections...")

    server = greenswitch.OutboundESLServer(
        bind_address="0.0.0.0",
        bind_port=5002,
        application=InboundCallHandler,
        max_connections=10,
    )

    # This blocks forever, handling connections
    server.listen()
