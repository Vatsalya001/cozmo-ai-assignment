# Capture protocol — one page

Follow this page exactly. No engineering knowledge needed. Total time per property: about 25 minutes.

## Before you start

| | |
|---|---|
| **Phone** | **Tier 1 needs an iPhone Pro** — it is the only tier that uses the LiDAR sensor. Tiers 2 and 3 need no LiDAR and work on any iPhone 15 or newer |
| **Install** | **Stray Scanner** from the App Store (free). Nothing else. |
| **Settings** | Camera app → Formats → **Most Compatible**. Video → **1080p at 30 fps**. **HDR off.** |
| **Room prep** | Turn on every light. Open blinds. Open all internal doors fully. Do not move furniture. |

## Tier 1 — LiDAR walk (about 4 minutes)

1. Open **Stray Scanner**, press record, and **stand still for 3 seconds** before moving.
2. Walk the property at **slow walking pace**, roughly 1 metre from the walls, following the walls all the way round each room.
3. Hold the phone **upright at chest height**, screen toward you, camera toward the wall.
4. In every room, **sweep the phone slowly down to the floor and up to the ceiling once** — a smooth 3-second arc each way. This is what makes ceiling height measurable.
5. Walk through every doorway **squarely, facing forward**, and pause for 2 seconds in the opening.
6. **Return to where you started and stand still for 3 seconds** before stopping the recording. Closing the loop is what keeps the plan from drifting.
7. Keep the whole walk **under 4 minutes**.

## Tier 2 — Video walk (about 2 minutes)

Same route, same pace, **recorded in Stray Scanner — not the Camera app**. Upright, no zoom, **under 2 minutes**. This tier infers depth but still needs the phone's pose track: a bare `.mov` carries none and `scanplan run` refuses it. Stray Scanner writes `odometry.csv` beside the clip, which is what the tier reads.

## Tier 3 — Photos (about 6 minutes)

For **each room**, standing in the doorway and then in two opposite corners:

- Take **5 to 8 photos** that overlap by about a third, covering all four walls.
- Take **one extra photo squarely facing each other doorway** in that room.
- Keep every photo **level and upright**. Do not zoom.

## What to avoid

- **Mirrors and glass** — approach at an angle, never point straight at them.
- **Fast motion** — turn your whole body slowly; never whip the phone round a corner.
- **Low light** — if a room looks dim on screen, add light before recording.
- **Wet or glossy floors** — dry them, or note it on the hand-off sheet.
- Never stop and restart a recording partway through a walk.

## Handing the files over

1. Stray Scanner → **Share** → export each capture folder, keeping its name and its `odometry.csv`. Never re-export the clip from the camera roll: that drops the pose track.
2. Photos → **one folder per room**, named after the room: `kitchen/`, `bedroom 1/`, `hallway/`.

Put all of it in one folder and copy it to the machine running the pipeline. Then run **one command per capture**:

```
scanplan run <folder or video>
```

The tier is detected automatically. Each run writes `result.json`, `plan.svg`, `summary.md` and `report.pdf`.
