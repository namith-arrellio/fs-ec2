from flask import Flask, request, Response
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# =============================================================================
# HARDCODED DATA (replace with database later)
# =============================================================================

STORES = {
    "store1.local": {
        "name": "Store 1",
        "did": "+17577828734",
        "gateway": "telnyx_store1",
        "caller_id": "+17577828734",
        "context": "store1",
        "park_slots": ["700", "701", "702"],
        "users": {
            "1000": {
                "password": "123456",
                "vm_password": "1000",
                "name": "Store 1 - Ext 1000",
                "toll_allow": "domestic,international,local",
            },
            "1001": {
                "password": "123456",
                "vm_password": "1001",
                "name": "Store 1 - Ext 1001",
                "toll_allow": "domestic,international,local",
            },
        },
        "ring_group": ["1000", "1001"],
    },
    "store2.local": {
        "name": "Store 2",
        "did": "+17372449688",
        "gateway": "telnyx_store2",
        "caller_id": "+17372449688",
        "context": "store2",
        "park_slots": ["700", "701", "702"],
        "users": {
            "1000": {
                "password": "123456",
                "vm_password": "1000",
                "name": "Store 2 - Ext 1000",
                "toll_allow": "domestic,international,local",
            },
            "1001": {
                "password": "123456",
                "vm_password": "1001",
                "name": "Store 2 - Ext 1001",
                "toll_allow": "domestic,international,local",
            },
        },
        "ring_group": ["1000", "1001"],
    },
}

# Map DIDs to domains for inbound routing
DID_TO_DOMAIN = {
    "7577828734": "store1.local",
    "17577828734": "store1.local",
    "+17577828734": "store1.local",
    "7372449688": "store2.local",
    "17372449688": "store2.local",
    "+17372449688": "store2.local",
}


# =============================================================================
# XML GENERATORS
# =============================================================================


def not_found_xml():
    """Return empty/not-found response"""
    return """<?xml version="1.0" encoding="UTF-8"?>
<document type="freeswitch/xml">
  <section name="result">
    <result status="not found"/>
  </section>
</document>"""


def generate_user_xml(domain, user_id, user_data, store_data):
    """Generate directory XML for a user"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<document type="freeswitch/xml">
  <section name="directory">
    <domain name="{domain}">
      <params>
        <param name="dial-string" value="{{^^:sip_invite_domain=${{dialed_domain}}:presence_id=${{dialed_user}}@${{dialed_domain}}}}${{sofia_contact(*/${{dialed_user}}@${{dialed_domain}})}}"/>
      </params>
      <user id="{user_id}">
        <params>
          <param name="password" value="{user_data['password']}"/>
          <param name="vm-password" value="{user_data['vm_password']}"/>
        </params>
        <variables>
          <variable name="toll_allow" value="{user_data['toll_allow']}"/>
          <variable name="accountcode" value="{domain}-{user_id}"/>
          <variable name="user_context" value="{store_data['context']}"/>
          <variable name="effective_caller_id_name" value="{user_data['name']}"/>
          <variable name="effective_caller_id_number" value="{user_id}"/>
          <variable name="outbound_caller_id_number" value="{store_data['caller_id']}"/>
        </variables>
      </user>
    </domain>
  </section>
</document>"""


def generate_inbound_dialplan_xml(domain, store_data):
    """Generate dialplan XML for inbound calls to a store"""
    ring_targets = ",".join(
        [f"user/{ext}@{domain}" for ext in store_data["ring_group"]]
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<document type="freeswitch/xml">
  <section name="dialplan">
    <context name="public">
      <extension name="inbound_{domain}">
        <condition>
          <action application="set" data="domain_name={domain}"/>
          <action application="set" data="transfer_context={store_data['context']}"/>
          <action application="set" data="ringback=${{us-ring}}"/>
          <action application="set" data="call_timeout=30"/>
          <action application="set" data="hangup_after_bridge=true"/>
          <action application="set" data="continue_on_fail=true"/>
          <action application="bridge" data="{{leg_timeout=30,ignore_early_media=true}}{ring_targets}"/>
          <action application="answer"/>
          <action application="sleep" data="1000"/>
          <action application="voicemail" data="default {domain} {store_data['ring_group'][0]}"/>
        </condition>
      </extension>
    </context>
  </section>
</document>"""


def generate_store_dialplan_xml(domain, store_data):
    """Generate dialplan XML for internal store context"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<document type="freeswitch/xml">
  <section name="dialplan">
    <context name="{store_data['context']}">
      
      <!-- Internal extension dialing -->
      <extension name="local_extension">
        <condition field="destination_number" expression="^(10[01][0-9])$">
          <action application="bridge" data="user/$1@{domain}"/>
        </condition>
      </extension>

      <!-- Park slots -->
      <extension name="park_slot">
        <condition field="destination_number" expression="^(?:park\\+)?(70[0-2])$">
          <action application="set" data="fifo_music=local_stream://moh"/>
          <action application="valet_park" data="{store_data['context']} $1"/>
        </condition>
      </extension>

      <!-- Outbound calls -->
      <extension name="outbound">
        <condition field="destination_number" expression="^(\\+?1?\\d{{10}})$">
          <action application="set" data="effective_caller_id_number={store_data['caller_id']}"/>
          <action application="bridge" data="sofia/gateway/{store_data['gateway']}/+1$1"/>
        </condition>
      </extension>

    </context>
  </section>
</document>"""


# =============================================================================
# MAIN ENDPOINT
# =============================================================================


@app.route("/freeswitch", methods=["POST"])
def freeswitch_handler():
    """Main handler for all FreeSWITCH XML requests"""

    logger.debug("=" * 60)
    logger.debug("Incoming FreeSWITCH Request:")
    for key, value in request.form.items():
        logger.debug(f"  {key}: {value}")
    logger.debug("=" * 60)

    section = request.form.get("section", "")

    # DIRECTORY REQUESTS
    if section == "directory":
        # Domain FreeSWITCH expects in the response
        response_domain = request.form.get("domain", "")

        # Domain to use for user lookup (sip_auth_realm has the real domain)
        lookup_domain = request.form.get("sip_auth_realm", "") or response_domain

        user = request.form.get("user", "")
        action = request.form.get("action", "")

        logger.info(
            f"Directory request: user={user}, lookup_domain={lookup_domain}, response_domain={response_domain}, action={action}"
        )

        if lookup_domain not in STORES:
            logger.warning(f"Domain not found: {lookup_domain}")
            return Response(not_found_xml(), mimetype="text/xml")

        store_data = STORES[lookup_domain]

        if user not in store_data["users"]:
            logger.warning(f"User not found: {user}@{lookup_domain}")
            return Response(not_found_xml(), mimetype="text/xml")

        user_data = store_data["users"][user]
        # Use response_domain in the XML, but data from lookup_domain
        xml = generate_user_xml(
            response_domain or lookup_domain, user, user_data, store_data
        )
        logger.debug(f"Returning user XML for {user}@{response_domain}")
        return Response(xml, mimetype="text/xml")

    # DIALPLAN REQUESTS
    elif section == "dialplan":
        context = request.form.get("Caller-Context", "")
        destination = request.form.get("Caller-Destination-Number", "")
        domain = request.form.get("variable_domain_name", "")

        logger.info(
            f"Dialplan request: context={context}, dest={destination}, domain={domain}"
        )

        # Handle PUBLIC context (inbound calls)
        if context == "public":
            clean_dest = destination.lstrip("+").lstrip("1") if destination else ""

            lookup_variants = [
                destination,
                clean_dest,
                f"1{clean_dest}",
                f"+1{clean_dest}",
            ]
            matched_domain = None

            for variant in lookup_variants:
                if variant in DID_TO_DOMAIN:
                    matched_domain = DID_TO_DOMAIN[variant]
                    break

            if matched_domain and matched_domain in STORES:
                store_data = STORES[matched_domain]
                xml = generate_inbound_dialplan_xml(matched_domain, store_data)
                logger.debug(f"Returning inbound dialplan for {matched_domain}")
                return Response(xml, mimetype="text/xml")
            else:
                logger.warning(f"No DID match for: {destination}")
                return Response(not_found_xml(), mimetype="text/xml")

        # Handle STORE contexts (internal calls)
        else:
            for store_domain, store_data in STORES.items():
                if store_data["context"] == context:
                    xml = generate_store_dialplan_xml(store_domain, store_data)
                    logger.debug(f"Returning store dialplan for context {context}")
                    return Response(xml, mimetype="text/xml")

            logger.warning(f"No store found for context: {context}")
            return Response(not_found_xml(), mimetype="text/xml")

    # CONFIGURATION REQUESTS
    elif section == "configuration":
        key_value = request.form.get("key_value", "")
        logger.info(f"Configuration request: {key_value} (returning not found)")
        return Response(not_found_xml(), mimetype="text/xml")

    logger.warning(f"Unknown section: {section}")
    return Response(not_found_xml(), mimetype="text/xml")


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


@app.route("/debug", methods=["GET"])
def debug_view():
    import json

    return Response(json.dumps(STORES, indent=2), mimetype="application/json")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
