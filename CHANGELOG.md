# Changelog

The version here is the one in `bobi_control_center/config.yaml`, which is what
Home Assistant compares to decide whether an update exists. Every change that
reaches the app image gets a new version and an entry below.

## 3.20.0

The household's lists get a screen, and the screens a family opens get a
warmer one.

### רשימות

The site showed exactly one list: `bobi_cc_task_snapshot` publishes
`todo.mshymvt_ynvn` and nothing else. The house has **eighteen** `todo` lists,
and the ones a family actually keeps — shopping, recipes, reminders, the family
list — were not among them.

There is now a `lists` family: one screen, one tile per list, entries inside it.
The colour is per subject rather than per state, so the shopping list is amber
every time you open it and nobody has to read the headings.

**Which lists appear is the bridge's decision, and that is not deference for
its own sake.** Only about half of those eighteen belong to people. The rest are
Bobi's own machinery: an activity log of 338 entries, a multimodal context store
keyed by chat id, a WhatsApp outbox. A screen that rendered "every list" would
put a conversation log carrying phone numbers in front of the family. So the
allowlist lives in the bridge, where the household controls it, and the screen
renders what it is handed — including a list this application has never heard
of, which gets the neutral tone rather than being dropped for being unfamiliar.

### A warmer ground

Slate is a cold grey with blue in it, and a whole page of it reads like a
control panel. `warm` is the same lightness with the hue turned the other way,
so a card looks like paper on a table. Indigo stays the identity; the warmth is
the surface under it, not a change of brand.

`Tile` is the new unit of layout for the household screens — bigger than
`Card`, with an icon chip and a colour. Every accent class is written out in
full rather than assembled: Tailwind compiles the classes it can see, so
`bg-${tone}-100` produces markup pointing at CSS that was never generated, the
card renders with no colour, and nothing reports a problem.

Two smaller decisions worth recording:

- **A count is of what is still open, not of what is on the list.** A badge
  reading "2" beside a shopping list with one thing left to buy is worse than
  no badge.
- **An empty list says something, and never "0".** An empty family list is the
  normal case, not a fault.

### The bottom bar stayed at five

It is built from `PRIMARY_NAV.length + 1`, so a sixth tab would have fitted
rather than broken — into about fifty points of width on a phone, under the
size a thumb reliably hits. So adding one meant removing one: `רשימות`
displaced `אוטומציות`, because shopping is opened daily and this house
currently has no smart rules at all. Automations keep their screen and their
place in "עוד".

### Not delivered

The bridge read script this screen needs, `bobi_cc_lists_snapshot`, is **not
written yet** — the Home Assistant tooling was unavailable for the whole of this
change. Until it lands the screen behaves exactly as the design intends for a
family the contract has not declared: it says so, and asks for no snapshot.

## 3.19.0

Everything that was actually broken, and an honest answer for the rest.

### A light can be turned on at a brightness

`bobi_cc_devices` published brightness and colour temperature as
`controllable: false, operations: []` whenever the light was off. The reading
really is absent then — but the *capability* is not, and `light.turn_on` carries
brightness in the same call. The effect was that no light in this house could be
turned on at a brightness: you turned it on, waited for the next poll, and only
then got a slider.

The bridge now publishes the control with a value of nothing, and
`bobi_cc_device_commit` binds an expected of nothing to a light that is off. The
binding still holds both ways — an expected of nothing against a light that is
*on*, or a number against a light that has since been switched off, is
`stale_preview` exactly as before. Run against the house: the living-room LED
went from off to brightness 40 in one confirmed change, `executed` and
`verified`, and the same commit repeated against the now-lit light was refused
as stale.

### Smart rules can be created

`bobi_cc_rules` had been claiming `create_supported: true` while the contract
listed `rule_create` under `not_supported` and no commit script implemented it.
One of the two was lying.

`bobi_cc_rule_commit` now has a create branch, and it does not write the rule
itself — it hands the request to `script.whatsapp_ai_rule_v2_add`, the one place
that knows the stored format and that already runs the duplicate check, the
conflict check against rules at the same target and time, and the execution
guard. The Control Center's preview and typed confirmation stand in for that
engine's own approval gate. No chat id goes in or comes back. Rated `high`, so
the confirmation word is typed rather than clicked: a rule is a standing
instruction to Bobi, and the family default would have put a scheduled "turn
everything off" behind a single button. Run against the house: a one-shot rule
created and deleted, both `executed` and `verified`.

Rewriting an existing rule is still not offered — a rule is a compound object
and the contract carries one value per item.

### The bridge's own `detail` block was being dropped

`detail` sits in `_ITEM_KEYS`, so `safe_detail` skipped it — and skipping is not
flattening. Every item's nested detail went on the floor: a device's domain,
area, capabilities and limits, and a rule's mode, command, days and time. That
is why the rules screen rendered an empty strip of badges, and why nobody had
noticed that the days it expected as `"mon"` arrive as `0`. It is merged in now,
through the same redaction, with the top-level extras winning.

### A camera that cannot answer no longer reads as fine

`camera.lia_local` reported `idle` for days while every attempt to fetch a
picture answered HTTP 500. Through the universal state table that became
*"ממתין"*, so the devices screen looked healthy while the cameras screen failed.
`idle` on a camera says only that nothing is streaming, and it now reads
*"לא משדרת"*. The word is chosen per domain, and the domain now reaches the
normalizer because of the fix above.

### `/health` no longer answers a question it was not being asked

`writes_enabled` meant two opposite things. On the adapter it meant "this
implementation may write without a bridge" — always false. In Home Assistant's
contract it means the household's master switch, which is **on**. `/health`
reported the first, so anyone checking whether writes worked read `false` while
commits were reaching the house. The adapter's flag is now
`unrestricted_writes`, and the master switch is deliberately not answered by the
health check: it costs a Home Assistant round trip, and the watchdog polls that
endpoint.

### The double no longer advertises more than the house does

`app/mock/management.py` declared every verb in `SPECS[resource].operations`,
while the live contract declares a subset. So every "the bridge did not declare
this" path was tested only against a bridge that declared everything. A family
payload may now carry its own `operations`, and
`tests/test_double_matches_the_house.py` configures the double with the live 3c
lists. Writing that test immediately reproduced the original bug inside the
double itself — the house says `add` where this application says `create`, and
an untranslated `add` was dropped by the closed set, leaving the calendar with
no operations at all.

### What is not a gap, checked rather than assumed

Three things stay in `not_supported`, and the reasons are recorded in the
contract and in the tests so they are not re-litigated:

- **Editing or deleting a calendar event.** Home Assistant publishes exactly two
  calendar services, `create_event` and `get_events`. Both other paths are
  WebSocket commands a script cannot reach. (The iCloud calendar also reports
  `supported_features: 1` — create only.)
- **Renaming anything.** There is no rename service anywhere in Home Assistant;
  an entity rename is a registry command.
- **The helper timer verbs.** The allowlist holds twelve curated ids — eight
  booleans, two numbers, a datetime and a select — and not one timer or counter.
  The house has 28 timers, but they are Bobi's own machinery: confirmation
  timeouts, guard timers, menu sessions. Exposing those to a web page would
  corrupt conversations in flight.

`CLAUDE.md` said fourteen `bobi_cc_*` services (it is 33, derived from `SPECS`),
said the master switch was off, and said not to touch Home Assistant at all —
which had stopped describing how the bridge work actually gets done. All three
are corrected.

## 3.18.1

Only the switch you pressed reacts.

3.18.0 made the pressed switch move at once, but left the other half of the
problem in place: `pending` was still handed the whole page's change state. It
does two things — it pulses the switch and it refuses further presses — so
turning on one light made **every** switch on the screen blink and go
unpressable until that light answered.

It is now per device. The pressed switch pulses and holds still; the rest are
untouched and remain usable.

`Switch`'s own documentation had gone stale in the same place, still promising
the knob "never guesses" and moves only after a read-back — which stopped being
true in 3.18.0. It now says what the component actually does: it shows what the
caller passes, the catalogue passes the pressed position and replaces it with
the bridge's answer, and `pending` belongs to one switch.

## 3.18.0

A switch moves when you press it.

### Where the delay actually was

Pressing a switch waited on three round trips before anything moved on screen:
a preview, a commit, and then a fresh snapshot. The third was the expensive
one, and it was expensive for a reason nobody intended.

The device catalogue is cached for sixty seconds because rendering
`bobi_cc_devices` is the slowest thing this app does. Switch positions are not
in that cache — `live_state.overlay` re-reads every one of them from
`/api/states` on every single request. The comment above the cache-drop said
exactly that, and then the code dropped the catalogue anyway, for every commit
including a light switch. So the very next read, the one the person who pressed
the switch is waiting on, could not use the cache and had to re-render the whole
template first.

It now drops the catalogue only for a commit that changed something the
catalogue actually carries — a temperature, a mode, a brightness. A power
commit keeps it, because `/api/states` already reports the only thing that
changed. A test asserts both halves: the toggle keeps the cache, the
temperature still throws it away.

### And the switch no longer waits to move

The card showed the bridge's value the whole time, so even with the read made
cheap there was still a preview and a commit to sit through. It now shows what
it was asked to do, immediately, per device — pressing one switch never moves
another.

This is not a claim that the change landed, and nothing was relaxed to do it.
The preview still happens, the commit still goes through the bridge, and the
read-after-write still decides the truth: the requested value is held only
until the bridge answers, and the switch then settles onto whatever it says —
springing back if the house refused. A commit that fails or cannot be verified
still opens the dialog to say so, and a refusal that comes back with the value
unchanged releases the switch rather than leaving it showing a request that is
never going to happen.

Home Assistant is still the only path. Nothing here talks to a device directly,
and no entity id or token reaches the browser.

## 3.17.1

The installed app says what its scope is, instead of leaving it to be worked out.

### Two fixes that were both wrong in opposite directions

iOS decides whether a home-screen icon opens as an app or as a page inside
Safari's chrome by comparing the current URL against the manifest's `scope`.
That comparison has now been got wrong twice:

* **before 3.12.1** the manifest said `"start_url": "./"` and `"scope": "./"`.
  Chromium resolves those against the manifest's own URL and gets the right
  answer; iOS has long handled relative values here poorly, and a scope it
  cannot resolve is a scope nothing is inside.
* **3.12.1** removed both, reasoning that the specification then *derives* them
  from the document that linked the manifest. That is what the specification
  says. It did not fix the phone, because the derivation is the unreliable part.

3.16.1 then found that the service worker had been serving the *old* manifest
from a cache whose key was never bumped — a real bug, and a necessary fix, but
not this one.

### Nothing left to derive

The manifest is now generated per request with **absolute** `start_url`,
`scope` and `id`, and absolute icon URLs. It cannot be a static file, because
this app is served from two places: a public hostname at the root, and a Home
Assistant Ingress prefix generated per session and unknown at build time.
`X-Ingress-Path` is what the proxy sends, carrying the prefix it stripped;
absent, the app is at the root.

| Served from | `scope` |
| --- | --- |
| the public hostname | `/` |
| Ingress | `/api/hassio_ingress/<token>/` |

Verified in a real browser rather than by reading the spec: the manifest
resolves to an absolute scope, and both the loaded page and a hash route
(`#/devices`) test as **inside** it. The response is `no-store` and `private`,
because the Ingress prefix belongs to one session.

A test asserts both shapes, and fakes the static directory rather than skipping
when no frontend is built — so it runs in CI instead of quietly passing by.

**This still needs the icon removed and re-added once**, after updating: iOS
keeps the manifest an installed icon was created with.

## 3.17.0

An update is a download now, not a build on the Raspberry Pi.

### The Supervisor was compiling this app on every release

There was no `image:` in the manifest, so the Supervisor did what it does
without one: it ran `docker buildx build` on the Pi itself. Every single time.

That is about two minutes of a Raspberry Pi 4 per release — 3.16.0 took 2:02,
3.13.0 1:48, 3.10.1 1:53 — and it is not idle time. The Supervisor answers
nothing while it runs: the logs for the 3.16.0 update carry
`Timeout connecting to Supervisor`, a failed `/host/info`, and a backup listing
that timed out. The 3.9.0 build did not merely stall, it failed outright and
left the update undone. Six releases in one afternoon meant twelve minutes of
that.

The manifest now names
`ghcr.io/inoncohen2/{arch}-addon-bobi_control_center`, and a workflow publishes
that image for each architecture when the version changes. The Pi pulls a
finished image.

### The part that had to be made safe

Naming an image removes the Supervisor's local-build fallback entirely: from
now on a version whose image was never published cannot be installed **at all**
— not slowly, not at all. Two things guard that:

* a test asserts every architecture in `arch:` is one the publish workflow
  actually builds, so the manifest cannot promise a platform CI never produces;
* the workflow's own `verify` job pulls each declared image **anonymously**,
  which is how the Supervisor pulls it. A package left private passes an
  authenticated check and then fails on the Pi, which is the worst possible
  moment to discover it.

A published tag is never rebuilt, so a version the Pi has already pulled cannot
come to mean a different image.

### armv7 dropped

The Supervisor warns the value is deprecated, and emulating that platform in CI
cost more than a platform nobody here runs. `aarch64` and `amd64` remain.

## 3.16.1

Two things that were reported from a phone, and were both real.

### The manifest fix from 3.12.1 never reached a phone

The service worker pre-caches the shell — `index.html`, `manifest.webmanifest`,
`icon-192.png` — under the cache key `bobi-shell-v1`, and answers everything
that is not a navigation **cache-first**. The key was never bumped when 3.12.1
rewrote the manifest, and `activate` only deletes caches whose key differs from
the current one. So the old manifest, the one still carrying `scope`, was
served from that cache for good.

That is why the fix appeared not to work: deleting the home-screen icon and
adding it again re-installed the same stale manifest, and iOS went on drawing
the out-of-scope bar with the domain in it. The reasoning that made the shell
cache-first — *"the name changes when the content does"* — is true of
`assets/index-<hash>.js` and of nothing else in that list.

The cache key is now `bobi-shell-v2`, so the stale copy is dropped on activate,
and every fixed-name shell file is fetched network-first with the cache as a
fallback. The app still opens with no signal; it just cannot pin a file whose
content it has no way to notice changing. A test now fails if a pre-cached
fixed-name file is not revalidated.

**This still needs the icon removed and re-added once**, after updating: iOS
keeps the manifest an installed icon was created with. The difference is that
this time the manifest it fetches is the corrected one.

### A light switch showed a dialog it was supposed to skip

3.13.0 made a switch apply at once, and it did — but the dialog opened anyway
while it worked. `startAndApply` sets the preview one tick before it commits,
and the dialog opens on *"a preview exists and we are not idle"*, so flipping a
light raised a modal reading **עדיין לא בוצע דבר** over a spinner, which then
closed itself when the commit landed. Against localhost that is a flicker;
from a phone, through Cloudflare, it is a dialog that sits there.

The change now stays silent for the whole gesture and speaks only when there is
something to say — the backend asked for confirmation, the write failed, or it
came back unverified. Nothing was relaxed: the preview, the token, the expected
state and the read-after-write are all still there, and a destructive change
still stops and asks.

## 3.16.0

Two more Shabbat clocks — one that turns things off, one that turns them on.

### They are clocks, not settings

Each carries its own switch, its own hour and its own device list. Both arrive
switched off, empty and at 00:00, so nothing happens until somebody sets one.
The switch and the hour appear on the clock's own card rather than in the list
of times, because two controls for one setting is how the same value gets
changed twice by someone who thought they were looking at two.

They run while **איסור מלאכה is in effect** rather than on a named weekday, so
they hold on Yom Tov as well as Shabbat, and a clock left with an hour in it
does nothing mid-week.

An added on-clock has no air conditioner settings of its own: a unit in its
list is switched on and keeps whatever it was already set to. The four original
profiles are unchanged.

### An empty helper is not a device called "unknown"

Found while testing this: a freshly created `input_text` sits at `unknown`, not
`""`. The token parse only rejected empty strings, so a new clock's device list
read as `['unknown']` — one phantom device, which is why the first commit
against it answered `stale_preview`. All three scripts now reject `unknown` and
`unavailable` alongside the empty string, which also hardens the four original
profiles against a helper that ever loses its value.

### Verified against the live install

The hour, the switch and the device list each previewed, committed and read
back; a device token outside the whitelist was refused on the new clocks
exactly as on the old ones. Every value used in testing was then set back, so
both clocks are off, empty and at 00:00 — nothing fires this Shabbat that would
not have fired before.

## 3.15.0

The cameras screen shows the cameras.

### The picture comes through the backend, not from Home Assistant

The browser asks this application for `cameras/<canonical id>/snapshot` and gets
bytes. It never learns the entity id behind a camera, and it never receives a
credential — which matters more here than anywhere else in the app, because the
`entity_picture` URL Home Assistant publishes carries the camera's own access
token, and that token is a working key to the stream for as long as it lives.
It is not read, and it does not leave the server. The frame is fetched with the
Supervisor token in a header, server-side.

Resolving a canonical id to an entity is a whitelist with two locks: the
mapping comes from the bridge's own camera catalogue, so only a camera the
household published can be named at all; and the resolved entity must be in the
`camera` domain, so a canonical id pointing at a switch cannot turn this into a
general image proxy. `laundry` is a real id in the catalogue and is refused.
Both failures answer the same plain 404, so guessing teaches nothing.

### A camera that is not there says so

`camera.lia_local` answers HTTP 500 on the live install, because the camera is
unplugged. That is the path this release could actually verify end to end, and
it is the one that had to be right: the screen says *המצלמה אינה זמינה כרגע*
rather than showing a broken image icon, which would read as a bug in the app.

### Nothing here can switch a camera on

The cameras screen still passes `readOnly`, and `CameraView` takes no change
handler at all — there is no control to disable, because none is rendered. The
adapter method is a read that takes a canonical id, so there is no parameter
through which a caller could ask it to act, and the architecture test that pins
the abstract adapter surface now names it explicitly as one.

The frame loads on entry and reloads only when a person asks. Polling a camera
would have made this the busiest thing in the house on a screen left open.

## 3.14.0

A Shabbat profile now sets how each air conditioner runs, not only how warm.

### Mode, fan speed and swing, per air conditioner, per profile

Until now a profile carried one number per air conditioner — its target
temperature — and ran it in `cool` because the executor said so, in a
hard-coded string nobody could see or change. Each air conditioner in an
on-profile now also publishes **מצב הפעלה**, **עוצמת מאוורר** and **הנפה**,
stored in `input_select` helpers and applied by `script.shabbat_apply_profile`.

The options are the ones the units actually accept, read from each unit rather
than assumed: the girls' air conditioner swings `off`/`on` and blows up to
`turbo`, the other two swing four ways and blow up to `full`. The write bridge
validates a choice against the helper's own option list, so the bridge that
reads and the bridge that writes cannot come to disagree about what is legal —
`turbo` is refused for a swing setting even though it is a valid fan speed.

Every helper's first option is what the executor already did — `cool`, `auto`,
`off` — so a profile that nobody edits behaves exactly as it did before.

Verified against the live install, end to end: a commit moved the salon's
swing from `off` to `vertical` and read it back; replaying the stale expected
value answered `stale_preview`; an option outside the helper's list answered
`invalid_value`. Nothing was relaxed to get there.

### A device with several settings keeps them together

The profile screen gathers a device's extra settings into its own sheet, keyed
by the device token. Two items cannot share an id, so a device with more than
one setting names each after itself — `profile.pre_on.ac_salon.hvac_mode` —
and the token is now the first segment of that name. Without this the three new
controls would each key themselves under a token no device has, and the sheet
would have opened empty rather than wrong.

## 3.13.1

The split read path from 3.11.0 is switched on.

### The bridge now names the entity behind each device

`script.bobi_cc_devices` publishes `entity_id` on every managed item. That was
the one line the 3.11.0 split was waiting for: the application cannot map a
canonical id to an entity by itself — that mapping is the household's and lives
in Home Assistant — so until the bridge said it, `entity_map` returned `{}`, the
overlay did nothing, and a switch position was only ever as fresh as the
60-second catalogue cache. Switch positions now come from `/api/states` on every
read, as designed.

No entity id reaches the browser. `entity_map` reads it from the raw payload
before the normalizer strips it, and the canonical model still has nowhere to
put one.

### The double had drifted from the bridge

Only one item in `app/mock/management.py` carried an `entity_id`, so almost
every test of the overlay ran against a payload no real bridge sends any more.
Each device item in the double now carries one, and a test asserts it stays
that way — the double mirroring the live bridge is where most of the serious
bugs in this project have been found.

## 3.13.0

The device catalogue acts on a tap, and a device's name opens everything it can
do.

### A switch applies at once

Flipping a light is not a decision anybody wants read back to them first. A
switch on the catalogue now previews **and** commits in one gesture, with no
dialog in the way.

Nothing was relaxed to do it. The preview still happens, so the preview token,
the expected state and every published limit are still checked; the commit
still goes through the bridge, so the Home Assistant master switch and the
read-after-write verification still hold. What was removed is a question, not a
guard — and *which* changes may skip the question is not a new judgement made
in the screen: it is the preview's own answer. A change the backend called
destructive, or for which it asked for a typed word, still stops and asks.
There is a test that fails if that stops being true.

It is quiet only when it works. A refusal, or a write that came back
unverified, opens the dialog to say so — the one thing worse than a question is
a change that did not happen and did not mention it.

### Tapping a device's name opens its controls

A device arrives from the bridge as several items: `ac_salon` carries the
switch, and `ac_salon_temperature`, `ac_salon_hvac_mode`, `ac_salon_fan_mode`,
`ac_salon_swing_mode` and `ac_salon_preset_mode` carry the rest of it. The
catalogue showed only the first, so everything an air conditioner can actually
do had nowhere to be operated from.

The sheet now gathers them — target temperature, mode, fan, swing, preset; an
LED's brightness and colour temperature; a vacuum's suction — found by the id
pattern the bridge already uses, so a device that gains a capability gains its
control with no change here. The rows drop the device's name from their labels,
which the sheet's title already carries, and the capability chips are Hebrew.

### The double, again

`MockManagementBridge` published one number per air conditioner where the house
publishes a switch plus an item per capability. The sheet had nothing to gather
from it, so the feature could not be seen to work until the double told the
truth.

## 3.12.1

The installed app went back to being a page with Safari's chrome around it.

That is the look iOS gives a navigation it considers **outside the app's
scope**, and the scope came from the manifest 3.10.0 added — before it, there
was no manifest at all and iOS used the legacy `apple-mobile-web-app-capable`
meta tag, which has no scope to be outside of.

The manifest declared `start_url` and `scope` as `"./"`. Chromium resolves that
against the manifest's own URL and gets the right answer; iOS has long handled
relative values here poorly, and a scope it cannot resolve is a scope nothing
is inside.

Both are now **omitted**, which is not a workaround but the more correct answer:
the specification then derives `start_url` from the document that linked the
manifest and `scope` from that. Verified to resolve correctly both at the root
of a domain and under a stand-in Ingress prefix — the two places this app is
served from, and the whole reason the values were relative to begin with. An
absolute `"/"` would have been wrong under Ingress; there is now nothing left
to resolve, so there is nothing left to resolve differently.

`id` went with them. It is optional, it exists to give an installed app an
identity across manifest changes, and an identity that does not match the one
an icon was installed with is a second way to be told this is not that app.

**An already-installed icon keeps the manifest it was installed with**, so this
fix reaches a phone only after the old icon is removed and the site added to
the home screen again.

## 3.12.0

Each Shabbat profile is its own card, and you work it rather than read it.

### One card per profile

The bridge publishes a profile as a flat list of dotted ids —
`profile.pre_on.devices`, `profile.pre_on.ac_salon` — and the generic editor
rendered exactly that: a picker, then three unrelated numbers, then the next
profile's picker. Nothing said which profile a row belonged to, or that a
temperature belonged to a device that was in one.

Now each profile is a card carrying its own time control and its own devices:

* **every device is a chip** — one tap on or off, which is the whole
  interaction for a light or a socket;
* **a device with more to set opens a sheet** — its own membership switch plus
  every extra control the bridge published for it *in that profile* — and the
  chip then reads back what was chosen: **מזגן סלון · 24°C**.

Which devices get a sheet is not a list kept in the screen. It is worked out
from the items the bridge sent, so it is right by construction. Today that is
the three air conditioners, because their temperature is the only per-device
setting the Shabbat bridge publishes — an LED, the scent diffuser and the
vacuum get plain chips because there is nothing more to say about them in a
profile. If the bridge starts publishing a brightness or a fan speed, those get
sheets too and none of this changes.

A time that a profile card carries is no longer repeated in the general timing
card. Two controls for one value is how the same setting gets changed twice by
someone who thought they were looking at two.

### A profile would have accepted a device that was never on offer

Found while making the test double match the live bridge. A list's permitted
values live in `constraints.allowed` by the specification and in `options` by
the live bridge's habit, and the check read only the first — so against a real
payload the allowed set was empty, the check was skipped entirely, and
`the_neighbours_boiler` was as acceptable as the kitchen light.

Both the refusal and the picker now read either. The frontend had the same gap
and it is closed the same way.

### The chips ignored the role

The generic rows ask `isOperable`; the new chips asked a shorter question of
their own and left the role out of it, so a viewer got a padlock on the row and
a tappable chip beside it. There is one definition of "may this be operated"
now, and both use it.

### The test double now matches the live Shabbat bridge

It published three groups of its own invention — timing, profiles,
temperatures — where the house publishes one group per profile with dotted ids
and a `multi_select` whose choices live in `options`. A screen written against
the real thing engaged with none of it, which is why the mismatch had to go
before any of the above could be seen to work.

## 3.11.1

Three faults visible in a photograph of the running app.

### You could only choose one device per Shabbat profile

The picker was a dropdown. It was meant to be a row of chips, and the reason it
was not goes two layers down: the live bridge calls a profile's device list
`multi_select`, which is not a kind this side knew, so the kind was *inferred*
— and inference asked "are there options?" before "is the value a list?". A
list of two devices with fifteen options became a single choice.

Both halves are fixed: `multi_select` is a known synonym for `list`, and a
value that is a list is now recognised as one **before** options are
considered, because a list can never be a single choice however many options
accompany it.

A list also reads its choices from `options` now, not only from
`constraints.allowed`. The documented home is `allowed`; the live bridge uses
`options`, so reading only the first left every picker with nothing to pick.

### "קיימת טיוטה שמורה של user_1_active"

The bridge sends `{"user_1_active": true}` — the key is the flag's name, not a
person's. It went into the middle of a Hebrew sentence as the name of a member
of the household.

A handle is now dropped rather than tidied into a guess. Whether *anyone* has a
draft is a separate question from *who*, and it had to become one: hiding the
handle also emptied the owner list, and an empty list read as "no drafts" — so
the first fix silently stopped the screen mentioning the draft at all.

## 3.11.0

The read path is split in two, by how often each half changes.

### What moved, and what did not

* The **catalogue** — which devices exist, their canonical ids, their Hebrew
  names, capabilities and limits — still comes from `script.bobi_cc_devices`,
  and is now cached for a minute. Keeping it there is deliberate rather than
  lazy: it is configuration the household edits *in Home Assistant*, and moving
  it into this add-on would mean a new release every time a lamp is renamed.
* The **live state** — what is on right now — comes from `/api/states`, which
  renders no template and has no shape to get wrong.
* **Writes did not move at all.** The kill switch, the preview token, the
  expected-state check and the read-after-write all live in the commit bridges,
  and all four were run against the house and verified in 3.9.1.

The caching is what makes this a saving rather than an extra round trip: the
template renders once a minute instead of once a refresh.

### Why, concretely

A bridge script renders the house through Jinja on every read. Three faults in
this release came from exactly that: a `datetime` that cannot be serialised out
of a template (which made one family answer **500 to every call**), a family
publishing `enabled` where every sibling publishes `controllable`, and a
`display` field holding a raw machine state. Jinja has no schema.
`/api/states` has nothing to get wrong.

### What it refuses to do

Only **switch positions** are refreshed. Numbers and choices keep the value the
bridge computed, because working those out would mean copying the whole
capability model into this application — the thing the contract-driven design
exists to avoid. Deciding whether a raw state means "on" still needs domain
knowledge, so `ON_STATES` duplicates a small, explicit table of it; a domain
absent from that table is never overlaid.

Everything fails soft, and most of the tests are about that: no entity map, an
unreachable `/api/states`, an entity Home Assistant never heard of, a domain
nobody thought about, a state of `unavailable` — each keeps the bridge's own
answer, which is exactly the screen that existed before this split. A commit
drops the cached catalogue, because a target temperature changed and then shown
stale for a minute would look like a write that never landed.

`/api/states` returns every entity in the house, and the overlay keeps only the
ones the bridge's catalogue already named. No Home Assistant entity id reaches
a browser — there is a test that renders a snapshot and asserts the entity id
is not in it.

### Not yet in effect

The overlay turns on when `bobi_cc_devices` publishes `entity_id` on each of
its items, which is the one thing the app cannot look up for itself. Until that
bridge change lands, `entity_map` is empty and the app behaves exactly as it
did before — which is the fail-soft path, working. The backend half is complete
and tested; it has **not** been exercised against the live house.

## 3.10.1

A pass over every menu against the **live house** rather than the test double —
each family's real payload run through this application's own normalizer. Three
things the double had been hiding.

### Every device row read its state in English

`display` is the field that holds the human reading, and the live
`bobi_cc_devices` fills it with the entity's raw state. Taking it verbatim put
"off", "cool", "docked", "idle" and "unavailable" on the rows of the busiest
screen in the app. The Hebrew that already existed only applied when a bridge
sent *no* display at all — which the double did, and the house does not.

A published display now goes through the same vocabulary a value would. A
bridge that sends real Hebrew still passes through untouched.

### Every air conditioner had four English menus

`hvac_modes`, `fan_modes`, `swing_modes` and `preset_modes` arrive from Home
Assistant as bare string lists. A bare list has no label but its own token, so
all three air conditioners offered "cool", "fan_only", "silent", "boost". The
labels are Hebrew now; the values a commit carries are still Home Assistant's
own tokens.

### What the live sweep confirmed

- **מכשירים** — 19 entities, 15 controllable. The vacuum publishes no `power`
  at all: it resolves to a start/stop switch plus pause, return-to-base and
  locate, which is exactly what 3.9.0 designed against a mock and this proves
  against the real one.
- **משימות** — four real tasks, writes enabled. `bobi_cc_tasks` reports
  `writes_enabled: false`, but the app reads `bobi_cc_task_snapshot`, which
  reports true. Checked rather than assumed.
- **משתמשים** — real profiles, phones masked to `••••7600`, and the two
  alert-default rows are `readonly`, so they render as readings.
- **אוטומציות** — 11 real automations, each a switch plus "הרצת אוטומציה עכשיו".
- **עזרים · סקריפטים · מערכת · שעון שבת** — real data, all Hebrew.
- **כללים · סצנות · יומן** — genuinely empty in this house: no smart rules, no
  scenes, no events in the next 30 days. Empty because the house is, not
  because a screen failed.
- The live contract parses to the right verbs per family, including the
  `add`→`create` translation the calendar's "אירוע חדש" form depends on.

## 3.10.0

An installable app, a Shabbat clock that says the hour, and the week's portion.

### The site installs to the home screen

There was no manifest, no service worker and no app icon — only a favicon. Now:
a web app manifest, a mark drawn as SVG and rendered to the sizes iOS and
Android ask for (including a maskable one with a proper safe zone), and a small
service worker.

Every path is relative, and that is the whole difficulty: Home Assistant serves
this add-on under a generated Ingress prefix that is unknown at build time, so
an absolute `/manifest.webmanifest` resolves to the Supervisor's root. Verified
under a stand-in prefix as well as at the root — manifest parsed, all four icons
served, worker active and scoped to the Ingress path rather than to `/`.

The worker caches the shell and **nothing** from `/api`. A cached reading is a
lie about a light that may since have been switched off.

### The Shabbat clock said `2026-08-28T15:51:00+00:00`

The bridge forwarded the `jewish_calendar` sensor, which holds a UTC instant.
So the card showed a timestamp rather than a time — and the wrong hour, this
house being three hours ahead. It now publishes a local clock: **18:51** and
**19:45**, with the full local instant kept beside it for anything that
computes rather than reads.

The normalizer coerces a timestamp to a clock as well, so this cannot come back
through a different bridge: a stamp carrying its own offset is rendered in it,
and a UTC one is converted where the system has a timezone database and left in
its own offset where it does not.

### …and the week now has a name

`פרשת כי תבוא`, with the Hebrew date under it and the festival when there is
one, all from the same integration. The two times are now the card's headline
rather than small print beside the parasha.

### Times are edited on a 24-hour clock

`<input type="time">` renders its text in the **browser's UI language**, which
no page setting reaches: with the browser locale forced to `he-IL`, Chromium
still drew "11:30 PM" on a Hebrew right-to-left screen. So the control is built
rather than borrowed — two selects, which open the same native wheel on a phone
and are unambiguous in every locale. Every time field in the app uses it.

## 3.9.2

Two screens stopped being read-only, for the reason the contract itself named.

`helpers` and `automations` were published with `operations: []` and the note
"גשר הכתיבה קיים אך טרם אומת מול Home Assistant" — a deliberate gate, not a
gap. Both bridges have now been run against this house and verified, so the
gate opened on its own terms rather than being lifted:

- **`script.bobi_cc_helper_commit`** — the Control Center's own end-to-end test
  switch, off → on → off. Both calls `executed: true, verified: true`, each
  read back against the helper's own state.
- **`script.bobi_cc_automation_commit`** — "ניקוי Preview שפג" disabled,
  re-enabled, and triggered. All three `executed: true, verified: true`. The
  automation is enabled, as it was found.

Every unverified verb stayed out: `rename` is implemented on neither bridge and
is not declared, and `scenes` stays at `operations: []` because this house has
no scenes.

The contract's `detail` for both families now records what was verified and
how, so the next reader does not have to take "אומת" on trust.

What this changes on the screens: עזרים becomes editable — Bobi's AI switch and
monthly cap, the smart-notification switches, the morning-summary time, the
home-status policy. אוטומציות gets a switch per automation plus
"הרצת אוטומציה עכשיו", which is the button 3.9.0 built and had nothing to bind
to. Everything still goes through preview → confirm → commit, still needs the
master switch, and is still refused on a stale expected value.

## 3.9.1

Home Assistant became reachable again, so the parts of this that had only ever
been reasoned about got run.

### The first writes against real hardware

`script.bobi_cc_device_commit` had never been called. It has now, on the
laundry socket, through the same call the application makes:

- a **stale expected value** was refused — `executed: false`,
  `reason: stale_preview`, and the socket did not move;
- the correct expected value **executed and verified** —
  `before: false, after: true`, confirmed against the entity's own state;
- the same call in reverse put it back — `before: true, after: false`;
- asking for the state it was already in returned `already_in_state` with
  `executed: false`.

`script.bobi_cc_automation_commit` was probed the same way without changing
anything: `confirmed: false` and a stale `expected_state` were both refused.
The house was left exactly as it was found.

### The HA-automations screen could not load at all

`script.bobi_cc_automations_snapshot` answered **500 to every call**. It built
its response with `state_attr(..., 'last_triggered')`, which returns a
`datetime` object, and a datetime inside a response variable cannot be
serialised to JSON. The same class of fault as the `HVACMode` enum earlier in
this release: a native Python object surviving into a template result.

It is now coerced with `.isoformat()`, once, in a loop rather than eleven
times.

### …and would still have been read-only if it had

The same script published `enabled: true` and no `controllable` key, where
every sibling snapshot publishes `kind`, `value` and `controllable`. The
application fails closed on exactly that: no `value` means the bridge could not
read the item, and no `controllable` means no. Every automation would have
rendered as an unreadable, unoperable row.

It now publishes the shape its siblings do — and the live payload, fed through
this application's own normalizer, comes back `kind=toggle`,
`primary_operation=disable`, `run_operations=['trigger']`: a switch and the
"run now" button, from real data.

### A status reading was being guessed into a switch

The live system snapshot publishes `kind: "status"` for its six health rows.
`status` is not a kind this application has, so it fell through to being
inferred from the value — and `bobi_health: true` inferred as a **toggle**.
Every one of those rows is `controllable: false`, so nothing was drawn and
nothing broke; but a health readout guessed to be a switch is one flag away
from a control that reports the house's health and pretends to set it.
`status`, `reading` and `info` now say what they mean.

### What the live contract still says

`automations` and `helpers` are published with **no operations** and the note
"גשר הכתיבה קיים אך טרם אומת מול Home Assistant". That is not a bug and it has
not been changed: both screens stay read-only until their commit bridges have
been verified the way the device bridge just was.

## 3.9.0

The run buttons from 3.8.0, finished — and the screens where they were still
missing because the decision was being made in the wrong place.

### A vacuum had no controls at all

The devices screen puts on/off on the card, so its settings section below
filtered out every toggle to avoid saying the same thing twice. A vacuum is a
toggle. It is also the one device that publishes pause, return-to-base and
locate — none of which a switch can express, and all three of which that filter
dropped. There was nowhere in the application to pause the vacuum.

"A toggle" and "a toggle its card fully covers" are not the same set, and the
screen had no way to tell them apart: a switch stands for `enable`, `disable`,
`set`, `power`, `start` and `stop` at once, and which one it picked depends on
whether the thing is currently on. That is bridge vocabulary, and it does not
belong on a screen.

So each item now carries `run_operations` — the verbs it has that the control
for its kind does not already send — worked out by the backend beside
`primary_operation`, which answers the neighbouring question. A screen renders
them as buttons and applies its own judgement about which it will put one tap
away; `delete` takes no payload and still does not get one.

### The automations screen promised something it did not do

Its own introduction says you can enable, disable, **run now** and rename from
there. The switch covered the first two; "run now" went nowhere. Every
automation row now carries "הרצת אוטומציה עכשיו" beside its switch — and it
came out of the same change, rather than being added to that one screen.

The helpers counter gained its increment, decrement and reset the same way.

### Smaller

- A script's and an automation's last run were timestamps
  (`2026-08-26 06:45`); they now say how long ago.
- `MockManagementBridge` has a vacuum. The house has one, and it is the busiest
  row the live vocabulary can produce — so it was the row nobody had ever
  looked at.

## 3.8.0

The rest of the screens, read the same way — the twenty routes, photographed at
iPhone size, checked for horizontal bleed, and read as Hebrew rather than
scanned as layout.

### A read-only kind was drawing an editable field

The backend answers `readonly` when it cannot work out how an item is edited.
It is a deliberate refusal: rendering an unknown kind as a text field would let
someone type a value the bridge never said it would accept.

The screen ignored it. `readonly` fell through to the same text box every other
kind ends at, so a calendar event — which arrives `readonly`, because Home
Assistant publishes no service that edits one — was drawn as a box holding
`2026-09-02T18:00:00` and a button that would have sent whatever you typed as
the event. The same box appeared on the scenes, scripts and system screens.

A `readonly` item is now a reading, everywhere, whatever else was advertised on
it, and there is a test that fails if it stops being one.

### …and hiding the controls that should have been there

The other half of the same bug. A scene is a reading — there is no value to
edit — but `activate` is a complete request on its own, and the scenes screen
exists to activate scenes. It offered no way to do it. Nor did the scripts
screen, nor the timer on the helpers screen, nor "undo the last action" on the
system screen.

The contract now publishes, per operation, whether it takes a payload. A row
with no editor offers a button for each verb that needs nothing else, under the
contract's own Hebrew label — so the screen still knows nothing about scenes,
scripts or timers. Verbs that need a value (`rename`, `set`) get no button, and
neither does `delete`: taking no payload is a fact, and putting it one tap away
is a judgement, made separately.

### Words that were not Hebrew

Home Assistant's vocabulary was reaching the screen untranslated, and nothing in
the app knew those strings were words rather than data.

- A scene read `ready`, a timer `idle`, the undo row `available`, a camera
  `streaming`. Values the bridge sends without a display of its own are now
  said in Hebrew, with anything unrecognised still passed through.
- The faults screen put `device` and `sensor` on a chip beside each fault.
- A device's class was printed as `camera`, `light`, `switch`.
- A calendar event read `2026-09-02 18:00 – 19:00`; it now reads
  "יום ד׳, 2 בספט׳" and "18:00–19:00", the hours held left-to-right so that an
  evening meeting stops appearing to end before it starts.
- A script's last run was a timestamp; it now says how long ago.
- A counter's limits read "99-0" for the same right-to-left reason. Now
  "מ־0 עד 99".

### Layout

- Every switch was making its row eight pixels wider than the card it sat in.
  Nothing overflowed visibly — the hit area is invisible — but each card was
  quietly able to scroll sideways. The hit area now grows only vertically,
  which is the only direction that was ever short.
- Three timer buttons on one row pushed the helpers screen 33 pixels wider than
  the phone. Run buttons wrap inside the card now.
- The bridge specification screen was 40,665 pixels long. Its full service
  contracts are behind a disclosure; the page is a quarter of that.

### The test double

`MockManagementBridge` claimed a calendar event could be edited, moved and
deleted. Home Assistant offers no service for any of the three — the live
bridge advertises nothing on an event — so the double was describing a system
nobody could build, and every test that used it was testing the wrong thing. It
now says what the live bridge says, and publishes the calendars an event may be
created in, which is the write that does exist.

## 3.7.0

A pass over every screen with the screens open — fifteen of them, photographed
at iPhone size, checked for horizontal bleed, and read.

### One pattern was wrong on four screens

Devices, the Shabbat clock, the rules and the household each had a good
read-only screen from Phase 2 and, since 3.0, a working management section
underneath it. Both were rendered. So every screen said everything twice: once
as a card you could not touch, and again, several thumb-lengths down, as the
field you actually needed. The editable copy was always the one you had to
scroll to find.

They are now one screen each. The control goes **on the thing it controls** —
a switch on the device, on the rule, on the person — and the separate section
appears only when there is no bridge to put a switch on, which is exactly when
the read-only screen is the right screen.

### The Shabbat clock

The worst of them, and the one that prompted this.

- **Choosing what turns on and off was a text box** holding
  `kitchen,dining,led_salon`. To add a device you had to know its internal
  token, type it, and get the commas right. That is not a control; it is trust
  in someone's memory. It is now one tappable chip per device, labelled the way
  the household names it, with the ones in the profile filled in.
- The profiles and the air-conditioner temperatures were printed twice — once
  as cards, once as fields. Now once, editable.
- The page is a little over half its former length.

### Everywhere

- **A managed toggle is a switch**, not a button reading "כבה". A button states
  the *action*; a column of them reads as instructions rather than a panel you
  can scan.
- **The household permissions matrix no longer runs off the screen.** A hard
  512px floor pushed a two-person household's second column past the edge with
  nothing to say it had gone.
- **Rules lost six locked "עריכה" buttons.** Rewriting a rule is a compound
  change no bridge implements, and saying so six times is furniture.
- **A published range reads `0–120 דק׳`**, not `0-120דק׳`.
- Two labels pointed at a "שליטה" section that no longer exists on their page;
  they now say where the control really is.

### And in the test double

The mock's rules were named one thing on the read side and another on the
management side. In the live house both take a rule's name from the same field,
and a screen joins them on it — so a double that disagreed with itself would
have made that join look broken here and work there, or the reverse, which is
worse.

## 3.6.0

A phone-first pass over the screens, done with the screens open rather than
from memory: the app was built, served with canned responses in the real
shapes, and photographed at iPhone size in both themes. Every change below is
something that was visibly wrong in those pictures.

### The bottom bar fits on one row

It was a five-column grid holding six items, so the sixth wrapped onto a second
row and took a thumb's worth of height from every page. The column count is now
derived from the number of destinations, so adding one can never quietly do
that again. The active tab gets a filled pill behind its icon, which reads at a
glance without relying on colour alone.

### A light turns on from the light

Turning one on used to mean: open the page, scroll past the whole catalogue to
a second list, find the same light again by name, press there. Each device row
now carries its own switch.

- **It asks; it does not act.** Pressing it opens the same preview → confirm →
  commit dialog as every other change, and the knob stays where the bridge says
  it is until a commit has been read back. A switch that slid over and slid
  back would be the interface lying twice.
- **The tap target is 44px** around a 28px track, which is the smallest a thumb
  reliably hits.
- **Fail closed, unchanged**: no contract entry, no declared operation, nothing
  marked controllable, master switch off — no switch. The section below the
  catalogue kept every device a second time; it now holds only what a switch
  cannot express, a target temperature or a fan mode.
- The catalogue and the management snapshot are keyed differently and the
  canonical id deliberately never reaches the browser, so the two are joined on
  the bridge's own `canonical` name — the same field on both sides, not two
  renderings that agree. A name is weaker than an id, so **a name shared by two
  switchable devices matches neither**: a missing switch is a bad afternoon,
  the wrong light going off in a child's room is worse.

### Density and honesty

- **Rows, not tiles.** Two-up tiles were too narrow for a name and a switch to
  share a line, so each grew to three rows and five devices filled the screen.
- **The state pill is gone where there is a switch** — it was the same fact
  twice, costing a row of height each time.
- **A device's group is in Hebrew.** The cards read `vacuum` and `people`.
- **Eleven filter chips scroll in one row** instead of wrapping onto three and
  pushing the devices below the fold.
- **The search icon no longer sits on the first characters** — its padding was
  physical while the text direction is not.
- The desktop header claimed *"מצב הדגמה — הנתונים מדומים"*. It has not been a
  demo since 2.0.0.

## 3.5.1

Five screens were telling people not to look for controls that were already
there.

The devices screen carried a banner reading *"שליטה במכשירים מהממשק תהיה זמינה
בשלב הבא. כרגע זו תצוגה בלבד"* — written in Phase 2, true then — while a live
`ManagedSection`, wired to the contract and to `bobi_cc_device_commit`, sat at
the very bottom of the same page, below the whole nineteen-card catalogue. A
person opened the page, read the first thing on it, and stopped. So did I:
every claim I made about devices being controllable was true of the API and
false of the screen.

Rules, the Shabbat clock, users and settings had the same banner over the same
working section. The dashboard's feature card said editing was coming in a
later phase; those toggles have been writable since 2.2.0.

- **The banners are gone.** The managed section states its own status from the
  contract — *"קריאה בלבד"* when a family has no commit bridge, *"ניהול עדיין
  לא הופעל"* when the master switch is off — and a sentence hard-coded beside
  it can only contradict it. That is the failure this architecture exists to
  prevent, and it had been sitting in the five oldest screens the whole time.
- **On the devices screen the controls come first**, above the catalogue.
- **An inert catalogue row now says where the working control is** rather than
  promising a phase that has arrived.
- Two architecture tests hold the line: no screen with a `ManagedSection` may
  carry a screen-wide read-only banner, and the shared label must point at a
  control rather than at a future.

One "next stage" survives, on the Shabbat drafts card, because it is still
true: nothing bridges draft management.

## 3.5.0

The five bridges that were missing — and the two that turned out to be
impossible, said so rather than faked.

3.4.1 left five families with a snapshot and no commit. Four of them now have
one. The fifth does not, and the reason is worth more than the bridge would
have been.

### What Home Assistant gained

- **`bobi_cc_system_commit`** runs the two safe checks and nothing else.
  Restart, Supervisor update, integration or device deletion, backup restore
  and anything shell-shaped are refused **by name, before dispatch**, so a
  contract that started advertising one tomorrow would meet the same answer.
- **`bobi_cc_script_commit`** runs one of two allow-listed Bobi scripts. The
  canonical id maps to an entity here and nowhere else, so the web cannot name
  a script to execute.
- **`bobi_cc_rule_commit`** switches a smart rule on or off, or deletes it,
  resolving the uid against the rules it can actually see.
- **`bobi_cc_calendar_commit`** creates an event.
- **`bobi_cc_scripts_snapshot`** now publishes its two entries as `action`
  items so a screen can draw a button for them.

### What is refused, and why

- **Scenes.** There are none configured in this house. A commit bridge would
  have been an allow-list with nothing in it, so it was not written.
- **Changing or deleting a calendar event.** Home Assistant publishes no
  service for either — that path is websocket-only and a bridge script cannot
  reach it — and neither mapped calendar advertises UPDATE in the first place.
  The snapshot had been advertising `edit`, `move` and `delete` on every event
  regardless: a fail-open, announcing three operations no bridge could carry
  out. Events are readings now, and say why.
- **Creating and rewriting a rule.** A rule is a compound object and the
  contract carries one value per item. Switching and deleting are offered;
  inventing a form for the rest is not.

Every operation the contract names has a bridge behind it, and every family
with an empty list has a snapshot and no commit. That is now checked by a test
that walks the whole contract rather than one family at a time.

### `action` — a kind that holds no value

The system bridge sends `kind: "action"` with no value, and every other kind in
the contract assumes an item *is* a value: a missing one means the bridge could
not read the item, which makes it unwritable. So both safe checks arrived
marked controllable and rendered as readings — the same shape of fault as the
vocabulary mismatch, one layer down.

`action` is now a kind of its own, exempt from the value requirement and from
nothing else. Forcing these into a toggle would have been worse than the bug: a
toggle says it can be switched back, and a self-check cannot.

### The calendar screen

Adding an event is the one calendar write that exists, so the screen now has a
form for it — reading the calendars it may write to from the contract's own
targets rather than a list kept here. Nothing is sent while typing; the button
opens the same preview → confirm → commit dialog as every other change, and the
backend refuses a payload missing a title or a time before a preview exists.

Nothing is relaxed. The master switch is still read-only and still off, and no
write has been run against hardware.

## 3.4.1

Commits now carry their target under the name the bridge actually reads.

Reconnecting to the live house and comparing every `script.bobi_cc_*_commit`
against what this side sends turned the settings bug found in 3.4.0 into a
pattern: this application names the target field per family — `user_id`,
`profile_id`, `helper_id`, `automation_id` — and five of the six bridges call
it `resource_id`. The field each script read arrived undefined, so **users, the
Shabbat clock, helpers and automations would have refused every write** as
`invalid_commit_request`. Nothing would have been written, and from this side
it would have looked exactly like a bridge declining the change.

The target is now sent twice: under the family's own field name and as
`resource_id`. One value, two names, and a script ignores the one it does not
use — which is also the only fix that suits a bridge written before this field
was named and one written after. The published bridge contract says so, so the
next bridge author reads it rather than discovers it.

## 3.4.0

The two sides now speak the same language, and the house is controllable from
the web.

Connecting to the live Home Assistant showed three families — users, the
Shabbat clock and devices — arriving fully described, marked controllable, and
entirely read-only. Nothing raised. Each verb the bridge declared was a verb
this side did not know, and a verb only one side knows is dropped in silence by
the closed-set filter: the contract announced the operation, the app quietly
did not offer it, and neither reported anything wrong.

Home Assistant's model was the right one. A family is a list of items each
holding a value, `set` sets it, and a device names one verb per capability.
The granular verbs were this application's idea.

### What changed here

- **`set` is accepted wherever the live bridge declares it** — users, the
  Shabbat clock, settings — beside the granular names, which still work where a
  bridge offers them.
- **Sixteen device capability verbs**, matching what the house publishes:
  `power`, `temperature`, `hvac_mode`, `fan_mode`, `swing_mode`, `preset_mode`,
  `brightness`, `color_temp`, `intensity`, `scent`, `timer`, `fan_speed`,
  `start`, `pause`, `stop`, `return_to_base` and `locate`.
- **Every refusal that used to key off a verb now reads the payload.** The
  last-admin guard catches a `set` that switches off the only administrator or
  demotes them; the phone door opens for a `phone` field under `set` as it did
  under `set_phone`, and the change is rated sensitive for what it carries
  rather than for what it is called.
- **`primary_operation`** — one item now carries several verbs, and nothing in
  the payload says which one sets the value it reports. An air conditioner
  reports a temperature and accepts `power` first, so a screen taking the first
  name in the list would have sent `power` when someone edited a temperature:
  the wrong change, previewed honestly, confirmed by a person who read a
  correct-looking dialog. The backend decides it once; no component guesses.
- **A switch verb is no longer checked against the item's own limits.**
  `power: true` measured against a °C range produced "the value must be a
  number" — the check being wrong about the request rather than the request
  being wrong. It is still checked against what a switch can hold.
- **A bare list of choices is understood.** `hvac_modes` and `fan_modes` are
  plain string lists in Home Assistant, and they were being dropped whole: a
  choice control with nothing to choose from.
- **A family declaring no operations is readable, not missing.** An empty
  `operations` list is the documented way to publish a snapshot bridge before
  its commit bridge exists, and it was reporting the family as unavailable —
  the difference between a screen full of values and a screen saying there is
  nothing here.

### What changed in Home Assistant

- **`bobi_cc_devices`** published `kind` as the Home Assistant domain —
  `light`, `climate` — where the contract asks for an editor kind, so every
  device fell through to read-only regardless of vocabulary. It now publishes
  one canonical item per controllable value, the way the Shabbat bridge already
  did: sixteen devices become thirty-one items, each with the limits and
  choices Home Assistant actually holds.
- **`bobi_cc_device_commit`** is new, and reaches only the sixteen canonical
  devices, only through a capability the device has, with the kill switch, the
  preview token, the expected-state match and read-after-write all enforced on
  that side too.
- **`bobi_cc_manage_contract`** declares the fourteen device verbs the commit
  bridge implements, and names `helpers`, `automations`, `scripts` and `scenes`
  — read-only, honestly, because their write path is not verified.
- **`bobi_cc_settings_commit`** read `resource_id` while this application sends
  `setting_id`, so every settings write would have been refused as
  `invalid_commit_request`. It accepts both now.

An item whose current value Home Assistant cannot read is published with a
reason and no control rather than with a guess — a light's brightness while it
is off, a mode the integration does not report. A preview binds to what the
bridge reports, so a guessed value would be a guess that got confirmed.

Nothing is relaxed. The master switch is still read-only and still off; the
preview token, the single-use expiry, the payload and observed-state binding,
the explicit confirmation, read-after-write and the closed service allow-list
all stand.

## 3.1.1

External authentication now remains fail-closed when Cloudflared rewrites the
origin `Host` header to the add-on's internal Docker hostname. Bobi recognizes
the paired headers that Cloudflare creates at its edge, while its unpublished
container port keeps that trust boundary inside Home Assistant's app network.

## 3.1.0

Bobi can now run at a dedicated HTTPS hostname through the existing Cloudflare
Tunnel while Home Assistant Ingress keeps working in parallel.

- Requests on the configured external hostname require a salted-scrypt
  password and a 12-hour, server-side session. The browser receives only a
  `Secure`, `HttpOnly`, `SameSite=Strict` session cookie.
- Login attempts are throttled, state-changing requests require the exact
  HTTPS origin, and an incomplete external configuration fails closed.
- Ingress continues to use Home Assistant authentication and needs no second
  login. There is still no published host port.
- The frontend includes a Hebrew login screen and logout control. Home
  Assistant credentials, raw entity IDs and raw services remain backend-only.

## 3.0.1

Support the complete Home Assistant management contract `3c` without filtering
the seven families added after tasks and features.

## 3.0.0

The complete management release — settings, users, the Shabbat clock, rules, the
calendar, devices and the system, all reachable from the web.

Home Assistant has not shipped those seven bridges yet, so the honest way to
build this was to **let the bridge describe them**. It names the items, says
which are operable, and supplies the limits; this side renders that description
in Hebrew and refuses whatever does not fit. Hard-coding seven contracts that do
not exist would have meant writing screens that assert what Bobi does, and
inventing the answer to a question only Home Assistant can answer.

The practical consequence: **every family works the day its bridge lands**, and
until then it says so. A family the contract does not name shows as unavailable
with the reason Home Assistant gave, never as a broken screen and never as a
control that silently does nothing.

### What is new

- **Eight API families**, each with a snapshot, a preview and a commit:
  settings, users, Shabbat, rules, the calendar, devices and the system, beside
  the tasks and features 2.2.1 already managed.
- **One editor for all of them.** `kind` picks the control, `constraints`
  bounds it, `options` fills it, `controllable` decides whether there is a
  control at all. A row the bridge did not mark operable is a reading.
- **Screens**: smart notifications, the calendar, cameras, the system, and a
  persistent activity log. Devices, the Shabbat clock, rules and users keep the
  read-only screens they already had and gain management underneath.
- **A trail that survives a restart.** Written to the app's `/data`, bounded and
  rotated, redacted on the way in — a number that never reaches the file cannot
  leak from it later.

### What it refuses

Four rules hold whatever the bridge says, because a bridge that has not shipped
cannot be relied on to catch them:

- A household never runs out of enabled administrators.
- A phone number is shown masked, and reaches the trail redacted. Setting one is
  the single field allowed past the private-field filter, and it is still never
  displayed or recorded whole.
- Saving a Shabbat profile changes the schedule and no device, and the dialog
  says so before anyone presses save.
- A control the bridge did not advertise is refused rather than passed along.

Restarting Home Assistant, updating the Supervisor, deleting an integration or a
device, and restoring a backup are refused for being what they are — checked
before the question of whether such an action exists is even asked, so a bridge
that started offering one tomorrow would meet the same answer.

Nothing from 2.2.1 is relaxed. The preview token, the five-minute single-use
expiry, the payload binding, the observed-state binding, the explicit
confirmation, read-after-write and Home Assistant's master switch all stand, and
the switch is still read-only: no endpoint, setting or screen can turn it on.

### Notes for the Home Assistant side

The seven new commit services receive the Phase 3A shape extended rather than
replaced — flat fields, the target under the name its bridge expects, one
`expected_*` per value the preview observed, plus `preview_token`, `confirmed`
and `request_id`. A bridge author who has read `bobi_cc_task_update_commit` can
write the next one without a new document.

Smart notifications and cameras have no bridge of their own by design: the first
are settings the contract marks with a `notification_class`, the second are
devices whose class is `camera`. Neither invents a service.

## 2.2.1

Commits now carry their preview token, which is what Home Assistant was asking
for all along.

2.2.0 was correct on both sides and wired wrongly between them. The preview
store held everything a commit needed, the bridge built a faithful service call,
and nothing passed the token from one to the other — `apply()` had no parameter
for it. Live testing with the master switch briefly on showed the script
receiving `user_id`, `summary`, `due_date`, `confirmed` and `request_id`, an
empty `token`, and answering `invalid_commit_request`. Nothing was written, on
either side of the failure, which is the flow behaving as designed.

- **The token is minted with the preview, never at commit time.** A value
  created when the commit arrives would prove nothing about a preview having
  happened, and proving exactly that is its whole job.
- **It is not the `preview_id`.** The id goes to the browser; the token stays in
  this process and is spoken only to Home Assistant. Someone who read the id out
  of a network tab still cannot drive `script.bobi_cc_*` themselves.
- **All three write services carry it** — `task_add_commit`,
  `task_update_commit` and `feature_commit` — alongside the `expected_*`
  evidence, never instead of it.
- **A tokenless commit is refused before a request is built**, and the test
  double now refuses one the way the live bridge does, so the gap cannot reopen
  unnoticed.
- `debug_http` logs the token's length rather than the token: a five-minute
  secret should not outlive the log file.
- Home Assistant's side is untouched. Its token requirement, whitelists,
  duplicate checks, `expected_*` comparison and read-after-write all stand, and
  the master switch remains read-only and off.

Feature state comes from the management contract, which now reports `enabled`
for all four targets. No raw `input_boolean` is read, then or now: a feature
whose state the contract does not report is shown but stays inoperable.

## 2.2.0

Phase 3A wired to Home Assistant's real write bridge.

Five `script.bobi_cc_*` services and nothing else: `manage_contract` and
`task_snapshot` (reads), `task_add_commit`, `task_update_commit` and
`feature_commit` (writes). `todo.*` and `input_boolean.*` are never called —
the allow-list holds fourteen `bobi_cc_*` names, pinned by a test.

- **The master switch is read, never set.** `writes_enabled` comes from the
  contract and is off today, so **previews work and commits are refused** with
  *"ניהול עדיין לא הופעל ב-Home Assistant"* — presented as a disabled feature,
  not a connection failure. No endpoint, setting or UI control can turn it on.
- **Two independent layers.** This application holds the preview token —
  server-side, random, five-minute TTL, single-use, bound to the operation, the
  target, the requested values *and the state observed at preview time*. Home
  Assistant re-checks its own whitelists, duplicates, `expected_summary` /
  `expected_status` / `expected_state` and read-after-write. Neither is relaxed
  because of the other.
- **Optimistic locking is honoured.** A bridge answering `stale_preview` means
  nothing was mutated, and the result says *השינוי לא בוצע*. `already_in_state`
  is reported as a verified success that needed no change.
- **The commit carries no payload.** Everything sent to Home Assistant comes
  from the stored preview, so a client cannot alter what it confirmed; an
  echoed `operation` or `resource_id` that disagrees is rejected outright.
- Tasks are driven by the management snapshot (open and completed, with the
  bridge's own `uid`); feature toggles by the contract's four feature ids. The
  AI master toggle and Fast Paths stay read-only — they are outside this
  contract.
- A feature whose current state the bridge does not report is shown but not
  operable: `expected_state` must be observed, never guessed.

## 2.1.0

Phase 3A: the management path, prepared and **fail-closed**.

Every change follows one flow — edit → preview → explicit confirmation →
commit → read-after-write verification → result — and it is enforced in the
service layer, so no route, adapter or screen can skip a step.

- **New endpoints.** `GET /api/bobi/manage/status`,
  `POST /api/bobi/manage/{tasks|features}/preview`,
  `POST /api/bobi/manage/{tasks|features}/commit`, `GET /api/bobi/manage/audit`.
- **Fail closed.** Management is discovered from a Home Assistant write bridge,
  never from configuration. No adapter declares one today, so every management
  request is refused with *"ניהול עדיין לא הופעל ב-Home Assistant"*. There is no
  fallback that calls a service anyway, and no environment variable that could
  enable one.
- **Tasks UI** for add, rename, complete, reopen and delete — each opening a
  Hebrew preview dialog rather than acting. Deleting warns and requires the
  confirmation word to be typed.
- **Feature toggles** show current and proposed state through the same dialog.
- **Audit** entries for every preview and commit, including refusals, carrying
  no phone number, LID or credential.
- The result is reported honestly as one of *השינוי בוצע ואומת*,
  *השינוי בוצע אך לא הצלחנו לאמת* or *השינוי לא בוצע*; nothing is shown as
  saved before the read-back agrees.

`writes_enabled` stays `false`, the bridge allow-list still holds only the nine
read/probe services, and no device control, Shabbat saving, rule creation,
automation editing, calendar write or permission change is exposed.

## 2.0.2

Two things the live 2.0.1 install still got wrong.

- **Overall health** — `status.ok` came back `null` while the bridge's own
  `healthy` flag sat in `details` as the string `"True"`. A canonical
  `health {status, ok, reason}` now resolves it from authoritative information
  only: the bridge's own statement first, otherwise the component states, where
  only an explicit failure counts. A component the bridge could not resolve
  leaves health `unknown` rather than dragging it to `false`, and `unknown` is
  rendered as unknown — never as a fault.
- **Shabbat AC temperatures** — the list was empty because the bridge keeps the
  temperatures inside each profile, not at the top level. They are collected
  from wherever they appear and de-duplicated by device. `temperature` is now
  numeric, with the bridge's own text preserved beside it.

`profile.active`, `profile.time` and `profile.offset_minutes` stay nullable: the
bridge has no authoritative value for all of them yet, and a guess is worse than
a null.

## 2.0.1

Normalization of real bridge responses, after the second live test.

- **Status** — WhatsApp, the AI fallback and its fast paths, the household,
  feature toggles and configuration health are first-class fields instead of
  text rows in `details`. The dashboard's health row is derived from them, since
  the real bridge sends no `components` array. Each section is accepted nested,
  bare or flat-prefixed.
- **Device limits** — the bridge's domain-specific constraints are kept in full
  (climate temperature range and mode lists, light colour temperature and
  brightness, scent intensity, slots and timer) rather than collapsed into
  `min`/`max`/`step`, which stay as a generic view.
- **Shabbat** — the pre-Shabbat offset is read from
  `upcoming.pre_offset_minutes`, profile device `tokens` are resolved through
  `device_labels` into `{id, label}` pairs, and `ac_temperatures` became a list
  so each temperature stays tied to its air conditioner.
- `/api/bobi/connection` reports `app_version`, so the UI no longer hard-codes it.

## 2.0.0

First release as a Home Assistant App: Ingress on port 8099, no external port,
`SUPERVISOR_TOKEN` used server-side only. Ten screens on the nine
`script.bobi_cc_*` bridge services, read-only throughout.

Shipped in two pushes — `8cc319a` normalized the real bridge responses and fixed
the diagnostics 502 **without bumping this version**, so the Supervisor never
offered it as an update. That mistake is what the version guards now prevent.
