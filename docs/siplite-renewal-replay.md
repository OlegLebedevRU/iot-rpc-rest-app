# RPC7011 renewal replay safety

Existing RPC7011 renews the ESP32 certificate identity. Its terminal RES and existing reboot/inventory behavior are unchanged; no new methods, events or peripheral commands are introduced.

Before the provisioning worker calls any PIN/setup/credential-changing procedure for a new cloud task, an internal-stack persistent owner commits a bounded task UUID/created_at fence. The existing positive integral created_at envelope field is required. An ambiguous storage failure does not authorize effects.

The existing latest saved result can be replayed. If that result was lost, superseded or never committed, the durable fence prevents repeating the renewal and returns an explicit replay-window/outcome-unknown failure. Sixteen recent identities plus an eviction watermark reject old unknown tasks conservatively. Operators reconcile the installed certificate identity and use a new task UUID for a new intent; this does not promise exactly-once behavior from the provisioning server.

Final RES publication requires successful persistence of the saved result. A reset after credential selector commit but before response persistence can therefore lose the response, but cannot repeat the old cloud renewal. Existing local authenticated provisioning and pending-key reconciliation remain available. No PIN or private key is placed in the replay fence.
