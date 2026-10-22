# Follow-up: independent viewer admission

Owner: MenuBuilder authorization/orchestration, coordinated with IoT and l4media.
This design task does not authorize new viewer leases in the first HEVC release.

Define a viewer subscription identity separate from publisher/input ownership.
Specify tenant, device, user/session, video:view policy and revocation checks;
bind the subscription to an existing real stream UUID and immutable descriptor.
Viewer join must not start a publisher, renegotiate codec or extend its lease.
Viewer leave/revoke must detach only its own PeerConnection. Publisher terminal
outcome must reach all authorized subscriptions, preserving structured error.
Stale epoch and cross-tenant requests must have no effect.

Before implementation, review this admission model jointly in TASK-30/40 and
specify API, persistence, expiry, quota, audit and independent-user integration
tests. Existing single lease/SN and owner/session checks remain authoritative.
