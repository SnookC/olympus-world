# Olympus World 1.2

Zeus, Hephaestus and Athena live on their own in a bare 3D world: a flat plain
under an open sky. Nothing is there unless they build it. Nobody gives them
tasks. They walk around, talk, build whatever they decide to build, read about
the real world on Wikipedia, and keep diaries. You watch.

This is a **new, separate program**. It does not touch your existing Olympus
install (C:\Olympus\olympus_campaigns), its databases, or its Gemini usage log.

## Install

Double-click **OlympusWorldSetup.exe**. It installs into `Documents\Olympus World`,
puts an **Olympus World** icon on your desktop, and adds an **Olympus World**
folder to the Start menu. It finds the Python you already have; nothing is downloaded.
(Windows may say "Windows protected your PC" because the installer isn't from a
big company: click **More info**, then **Run anyway**.)

Installing a newer version over the top keeps the gods' world, your settings
and your Gemini key. If the world is running, the installer asks it to save and close first. Uninstall from Windows' Apps list; it asks before deleting
their world (default: keep it).

## Icons you'll use

| Icon | What it does |
|---|---|
| **Olympus World** (desktop) | Starts the world and opens the viewer. A minimized "Olympus World" window appears in the taskbar: close it to stop the world (it saves first). Clicking the icon again while it's running just reopens the viewer. |
| Start menu > Olympus World - Check setup | Runs the tests, checks Ollama, asks Zeus for one real thought. |
| Start menu > Olympus World - Add Gemini key | Optional. Saves your Gemini key on this PC (typing is hidden). |
| Start menu > Olympus World - Test mode (no AI) | A separate pretend world with random actions. |

The viewer lives at http://127.0.0.1:8788/ (only this PC can open it; Goldmire keeps its own port).
No installer? Unzip the folder and use the .cmd files: they do the same things.

## Updates (1.2)

The world checks GitHub (github.com/SnookC/olympus-world) every few hours. When a newer
version is out, a gold **Update to …** button appears at the top of the side panel.
Press it, then **Update now**: it downloads the new version, checks it, backs up the
files it replaces (in the `backups` folder, last 3 kept), swaps them in and restarts
the world in the same window. If anything goes wrong it puts the old version back.
An update never touches the gods' world (`data`), your settings or your Gemini key.
You can also click **check for updates** under the version number.

## How their minds work

- **Everyday thoughts** use the free local model (`qwen2.5:7b` via Ollama).
- **Big moments** (the nightly diary reflection, and designing a large
  building) use Gemini, capped at **20 requests a day**. After the cap, or if
  Gemini fails, they use the local model instead.
- **Web**: Wikipedia only, read-only, capped at **30 reads a day**. Only the
  search words leave your PC. They can't post, buy, sign up or download anything.
- One game day = 60 real minutes. Time only passes while the world is running.

## What they can do

move · talk · build · design a big project and build it over time · add to anyone's
building · demolish their own buildings · **invent** reusable objects ·
**shape the world** · search Wikipedia · write in their diary · rest

**Building kit (1.1):** 12 shapes (box, cylinder, pyramid, sphere, cone, dome, arch,
stairs, wedge, ring, tree, bush), 16 materials, any colour, rotation, and parts that
**glow** at night. Up to 20 parts per build and 120 per big project.

**Inventions (1.1):** a god designs something once (a column, a lamp, a fountain)
and from then on anyone can place it in their builds by name, at any size or angle.
The Inventions tab shows who invented what and how often it's used.

**Keeping them from getting stuck (1.3):** a place with 150 parts is **finished**:
nobody can add to it, so the gods move on to something new. If a god picks the same
thing over and over (or spends most turns just walking), it's told it's stuck and
shown what it hasn't tried lately. A god that keeps one goal for 3+ game days is asked
to rethink it, and the nightly reflection asks for something Olympus doesn't have yet.
A god saved mid-thought (the world closed while it was thinking) is freed on start-up;
before 1.3 that god was skipped forever.

**Shaping the world (1.1):** a god can change the weather (clear, cloudy, rain,
snow, mist, storm), the sky, horizon and ground colours, fog and clouds. After a
change the world needs a few game hours to settle before anyone can change it again.

## Your controls (watch only)

- Drag to rotate, scroll to zoom, right-drag to pan.
- Click a god to follow them and see their goal, thoughts and who they're becoming.
- Side panel: Live, Diaries, Web, Talk, Places, Inventions.
- **Pause** freezes time and thinking.

## Where things are saved

- `data\world.json`: the whole world (saved every 10 seconds and on exit)
- `data\memory\<god>.jsonl`: every memory each god has ever had
- `data\usage.json`: today's AI and web usage
- `config\settings.json`: caps, models and speed (edit with Notepad)
- `config\secrets.env`: your Gemini key (private, never share)

To start a fresh world: stop it, then rename the `data` folder to `data_old`.
