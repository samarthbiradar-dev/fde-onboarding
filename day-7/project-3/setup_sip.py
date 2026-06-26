"""Project 3 — Run once to configure LiveKit SIP inbound trunk + dispatch rule.

Creates:
  1. LiveKit inbound SIP trunk  (accepts calls from Plivo)
  2. LiveKit SIP dispatch rule  (routes each call to a new room, auto-dispatches "receptionist" agent)

Then prints the exact values you need for Plivo Zentrunk.

Run:
    python setup_sip.py
"""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from livekit import api


async def main():
    lk = api.LiveKitAPI(
        url=os.environ["LIVEKIT_URL"],
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    )

    plivo_number = os.environ.get("PLIVO_NUMBER", "+912269985969")

    # ── 1. Inbound SIP trunk — reuse existing if already created ─────────────
    print("Checking for existing inbound SIP trunk...")
    existing = await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())
    trunks = existing.items if hasattr(existing, "items") else []
    existing_trunk = next((t for t in trunks if t.name == "plivo-inbound"), None)

    if existing_trunk:
        trunk_id = existing_trunk.sip_trunk_id
        print(f"  ✓ Reusing existing trunk ID: {trunk_id}")
    else:
        print("Creating LiveKit inbound SIP trunk...")
        trunk_resp = await lk.sip.create_inbound_trunk(
            api.CreateSIPInboundTrunkRequest(
                trunk=api.SIPInboundTrunkInfo(
                    name="plivo-inbound",
                    numbers=[plivo_number],
                )
            )
        )
        trunk_id = trunk_resp.sip_trunk_id
        print(f"  ✓ Trunk ID: {trunk_id}")

    # ── 2. Dispatch rule — one room per call, auto-dispatch receptionist ──────
    print("Creating SIP dispatch rule...")
    rule_resp = await lk.sip.create_dispatch_rule(
        api.CreateSIPDispatchRuleRequest(
            name="receptionist-rule",
            trunk_ids=[trunk_id],
            rule=api.SIPDispatchRule(
                dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                    room_prefix="call-",
                )
            ),
            room_config=api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name="receptionist")]
            ),
        )
    )
    rule_id = rule_resp.sip_dispatch_rule_id
    print(f"  ✓ Dispatch Rule ID: {rule_id}")

    await lk.aclose()

    print("\n" + "=" * 60)
    print("LiveKit SIP side: DONE")
    print("=" * 60)
    print(f"  Trunk ID   : {trunk_id}")
    print(f"  Rule ID    : {rule_id}")
    print(f"  SIP Domain : sip.livekit.cloud")
    print()
    print("Now configure Plivo Zentrunk:")
    print("-" * 60)
    print("1. Go to console.plivo.com → Voice → Zentrunk → Create Zentrunk")
    print("2. Give it a name, e.g. 'livekit-trunk'")
    print("3. Under 'Origination':")
    print("     URI     : sip.livekit.cloud")
    print("     Port    : 5060")
    print("     Transport: UDP")
    print("4. Save the Zentrunk — note its SID")
    print()
    print("5. Go to Phone Numbers → your number (+912269985969)")
    print("   → change Application to your new Zentrunk SID")
    print("   → Save")
    print()
    print("After that: start the receptionist agent (project-5/) and call")
    print(f"  {plivo_number} — it should reach your LiveKit agent.")


if __name__ == "__main__":
    asyncio.run(main())
