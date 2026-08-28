---
name: pvc-gel-memory
description: PVC gel soft actuator research memory. Use when the user mentions PVC in contexts involving plasticized PVC gel, soft actuators, artificial muscles, soft robotics, robotic fish/fishtails, wearable assistance, rehabilitation devices, electroactive polymers, actuator modeling/control, PVC:DBA materials, mesh electrodes, multilayer/stacked actuators, electric creep, space charge, Maxwell stress, or related papers by Chenyuan Dong, Li & Hashimoto, Asaka & Hashimoto, Frank, Al-Rubaiai, Shibagaki, or Wang.
---

# PVC gel Memory

## Overview

Use this skill to interpret the user's PVC-related research shorthand accurately. In soft actuator contexts, default "PVC" to plasticized PVC gel soft actuator, not ordinary rigid PVC plastic.

## Default Interpretation

- Treat PVC gel as an electroactive soft actuator material based on plasticized PVC, commonly PVC + DBA + THF.
- Preserve the distinction between fixed experimental examples and reusable design principles. Do not treat a paper's dimensions, layer count, voltage, or joint count as universal.
- Use Chenyuan Dong 2022 primarily as the abstract design template: multilayer PVC gel actuators arranged antagonistically to drive multi-joint oscillating mechanisms, with voltage/frequency and resonance shaping motion.
- For detailed parameters, models, and paper-specific conclusions, read `references/pvc-gel-key-notes.md`.

## Answering Guidance

When answering PVC gel questions:

1. Start from the user's immediate goal: material explanation, actuator design, model/control, fabrication, or literature summary.
2. Use the shortest relevant memory from `references/pvc-gel-key-notes.md`.
3. Say explicitly when a number is paper-specific rather than generally fixed.
4. Prefer reusable abstractions: layer count tunes displacement/output, area tunes force, membrane thickness/electrode spacing affects voltage, mesh and preload affect creep/contact/force transfer.
5. If the user asks for a design, derive dimensions from target force, displacement, frequency, workspace, and safety constraints instead of copying Dong's fish-tail dimensions.
