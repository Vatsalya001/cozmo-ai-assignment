# Capture protocol — one page

Follow this page exactly. No engineering knowledge needed. Total time per property: about 25 minutes.

## Before you start

| | |
|---|---|
| **Phone** | iPhone Pro (LiDAR tier) · iPhone 15 or newer (video and photo tiers) |
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

Same route, same pace, using the stock **Camera app** in video mode. Hold the phone upright. Do not zoom. Keep it **under 2 minutes**.

## Tier 3 — Photos (about 6 minutes)

For **each room**, standing in the doorway and then in two opposite corners:

- Take **5 to 8 photos** that overlap by about a third, covering all four walls.
- Take **one extra photo squarely facing each other doorway** in that room.
- Keep every photo **level and upright**. Do not zoom.

## What to avoid

- **Mirrors and glass** — do not point straight at them. Approach at an angle.
- **Fast motion** — never whip the phone round a corner. Turn your whole body slowly.
- **Low light** — if a room looks dim on screen, turn on more light before recording.
- **Wet or glossy floors** — dry them, or note it on the hand-off sheet.
- Do not stop and restart a recording partway through a walk.

## Handing the files over

1. Stray Scanner → **Share** → export the capture folder (keep the folder name).
2. Camera roll → export the walkthrough video as **.mov**.
3. Photos → **one folder per room**, named after the room: `kitchen/`, `bedroom 1/`, `hallway/`.

Put all of it in one folder and copy it to the machine running the pipeline. Then run **one command per capture**:

```
scanplan run <folder or video>
```

The tier is detected automatically. Each run writes `result.json`, `plan.svg`, `summary.md` and `report.pdf`.
