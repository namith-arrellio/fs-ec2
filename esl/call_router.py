# MUST be at the very top, before any other imports
from gevent import monkey

monkey.patch_all()

import gevent
import greenswitch
import logging

logging.basicConfig(level=logging.DEBUG)  # DEBUG for troubleshooting


def get_route_from_backend(called_number, caller_id):
    """Hardcoded routing logic - no database"""
    normalized = (
        called_number.replace("+1", "")
        .replace("-", "")
        .replace(" ", "")
        .replace("+", "")
    )

    if normalized == "7577828734" or called_number == "17577828734":
        logging.info(f"Routing call to Store 1: {called_number}")
        return {
            "action": "bridge",
            "targets": ["user/1000@store1.local", "user/1001@store1.local"],
            "context": "store1",
            "domain": "store1.local",
        }

    if normalized == "7372449688" or called_number == "17372449688":
        logging.info(f"Routing call to Store 2: {called_number}")
        return {
            "action": "bridge",
            "targets": ["user/1000@store2.local", "user/1001@store2.local"],
            "context": "store2",
            "domain": "store2.local",
        }

    return {"action": "reject", "reason": "No route found for " + called_number}


class InboundCallHandler(object):
    """Handle inbound calls from FreeSWITCH via Outbound ESL"""

    def __init__(self, session):
        self.session = session
        logging.info("🔌 New FreeSWITCH connection received!")

    def run(self):
        """Main function called when FreeSWITCH connects for a call"""
        try:
            self.handle_call()
        except:
            logging.exception("Exception raised when handling call")
            self.session.stop()

    def handle_call(self):
        """Process the inbound call"""
        # CRITICAL: Subscribe to events for this call
        self.session.myevents()
        logging.debug("myevents sent")

        # Keep receiving events even after hangup
        self.session.linger()
        logging.debug("linger sent")

        # Get call variables from session_data (populated by connect())
        # Note: Variable names differ from ESL inbound mode!
        called_number = self.session.session_data.get("Caller-Destination-Number")
        caller_id = self.session.session_data.get("Caller-Caller-ID-Number")
        uuid = self.session.session_data.get("Unique-ID")
        profile = self.session.session_data.get("variable_sip_profile_name", "")

        logging.info(f"📞 Inbound call: {caller_id} -> {called_number} (UUID: {uuid})")

        # Get routing decision
        route = get_route_from_backend(called_number, caller_id)
        logging.info(f"Routing decision: {route['action']}")

        if route["action"] == "bridge":
            # Set channel variables using call_command instead of setVariable
            self.session.call_command("set", f"domain_name={route['domain']}")
            self.session.call_command("set", "ringback=${us-ring}")
            self.session.call_command("set", "call_timeout=30")
            self.session.call_command("set", "hangup_after_bridge=true")
            self.session.call_command("set", "continue_on_fail=true")

            self.session.answer()
            logging.debug("answered")
            gevent.sleep(0.5)

            targets = ",".join(route["targets"])
            bridge_string = f"{{leg_timeout=30,ignore_early_media=true}}{targets}"
            logging.info(f"Bridging to: {targets}")

            self.session.bridge(bridge_string, block=False)
            logging.info("✓ Bridge command sent")

        elif route["action"] == "reject":
            logging.info(f"✗ Rejecting: {route.get('reason')}")
            self.session.hangup(route.get("reason", "CALL_REJECTED"))

        # Close the socket
        self.session.stop()


if __name__ == "__main__":
    logging.info("Starting OutboundESLServer on 0.0.0.0:5002...")
    logging.info("Waiting for FreeSWITCH connections...")

    server = greenswitch.OutboundESLServer(
        bind_address="0.0.0.0",
        bind_port=5002,
        application=InboundCallHandler,
        max_connections=10,
    )

    # This blocks forever, handling connections
    server.listen()
