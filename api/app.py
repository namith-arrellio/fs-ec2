from flask import Flask, request, Response
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# =============================================================================
# DATA
# =============================================================================

STORES = {
    "store1.local": {
        "name": "Store 1",
        "did": "+17577828734",
        "gateway": "telnyx_store1",
        "caller_id": "+17577828734",
        "context": "store1",
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
    },
    "store2.local": {
        "name": "Store 2",
        "did": "+17372449688",
        "gateway": "telnyx_store2",
        "caller_id": "+17372449688",
        "context": "store2",
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
    },
}

GATEWAYS = {
    "telnyx_store1": {
        "username": "testarrellio",
        "password": "your_password_here",
        "realm": "sip.telnyx.com",
        "proxy": "sip.telnyx.com",
        "register": "true",
        "caller_id_in_from": "true",
    },
    "telnyx_store2": {
        "username": "1009",
        "password": "your_password_here",
        "realm": "sip.telnyx.com",
        "proxy": "sip.telnyx.com",
        "register": "true",
        "caller_id_in_from": "true",
    },
    # Add more gateways dynamically here
}

ESL_HOST = "127.0.0.1"
ESL_PORT = "5002"


def not_found_xml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<document type="freeswitch/xml">
  <section name="result">
    <result status="not found"/>
  </section>
</document>"""


def generate_sofia_conf_xml():
    """Generate sofia.conf.xml with dynamic gateways"""
    gateway_xml = ""
    for gw_name, gw_data in GATEWAYS.items():
        gateway_xml += f"""
        <gateway name="{gw_name}">
          <param name="username" value="{gw_data['username']}"/>
          <param name="password" value="{gw_data['password']}"/>
          <param name="realm" value="{gw_data['realm']}"/>
          <param name="proxy" value="{gw_data['proxy']}"/>
          <param name="register" value="{gw_data.get('register', 'true')}"/>
          <param name="caller-id-in-from" value="{gw_data.get('caller_id_in_from', 'true')}"/>
        </gateway>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<document type="freeswitch/xml">
  <section name="configuration">
    <configuration name="sofia.conf" description="sofia Configuration">
      <global_settings>
        <param name="log-level" value="0"/>
      </global_settings>
      <profiles>
        <profile name="external">
          <gateways>
            {gateway_xml}
          </gateways>
        </profile>
      </profiles>
    </configuration>
  </section>
</document>"""


def generate_user_xml(domain, user_id, user_data, store_data):
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


def generate_dialplan_xml(context, store_data=None):
    """Dialplan with dynamic park slots + ESL routing"""

    if store_data and store_data.get("park_slots"):
        park_regex = "|".join(store_data["park_slots"])
        park_extension = f"""
      <extension name="park_slot">
        <condition field="destination_number" expression="^(?:park\\+)?({park_regex})$">
          <action application="set" data="fifo_music=local_stream://moh"/>
          <action application="valet_park" data="{context} $1"/>
        </condition>
      </extension>"""
    else:
        park_extension = ""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<document type="freeswitch/xml">
  <section name="dialplan">
    <context name="{context}">
      {park_extension}
      <extension name="esl_routing">
        <condition field="destination_number" expression="^(.*)$">
          <action application="socket" data="{ESL_HOST}:{ESL_PORT} async full"/>
        </condition>
      </extension>
    </context>
  </section>
</document>"""


@app.route("/freeswitch", methods=["POST"])
def freeswitch_handler():
    section = request.form.get("section", "")

    # DIRECTORY
    if section == "directory":
        response_domain = request.form.get("domain", "")
        lookup_domain = request.form.get("sip_auth_realm", "") or response_domain
        user = request.form.get("user", "")

        logger.info(f"Directory: {user}@{lookup_domain}")

        if lookup_domain not in STORES:
            return Response(not_found_xml(), mimetype="text/xml")

        store_data = STORES[lookup_domain]

        if user not in store_data["users"]:
            return Response(not_found_xml(), mimetype="text/xml")

        xml = generate_user_xml(
            response_domain or lookup_domain,
            user,
            store_data["users"][user],
            store_data,
        )
        return Response(xml, mimetype="text/xml")

    # DIALPLAN
    elif section == "dialplan":
        context = request.form.get("Caller-Context", "")
        logger.info(f"Dialplan: context={context}")

        # Find store by context
        for store_domain, store_data in STORES.items():
            if store_data["context"] == context:
                xml = generate_dialplan_xml(context, store_data)
                return Response(xml, mimetype="text/xml")

        # Public or unknown - no park slots, just ESL
        xml = generate_dialplan_xml(context)
        return Response(xml, mimetype="text/xml")

    elif section == "configuration":
        key_value = request.form.get("key_value", "")
        logger.info(f"Configuration request: {key_value}")

        if key_value == "sofia.conf":
            xml = generate_sofia_conf_xml()
            return Response(xml, mimetype="text/xml")

        # Return not found for other configs (use static files)
        return Response(not_found_xml(), mimetype="text/xml")

    return Response(not_found_xml(), mimetype="text/xml")


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
