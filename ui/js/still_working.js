// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Mario Carabotta

// How long a wait may go without news before the page says it is still
// working, and the words it says (the loading screen work). Shared by the loading screen,
// Home opening after onboarding (the second onboarding review fixes) and the result screen's scan (the first scan screen), so
// they always wait the same and say the same (the onboarding tidy-up). The loading screen's
// own words are written in index.html, kept the same by a test.

export const STILL_WORKING_MS = 10000;
export const STILL_WORKING = "Still working…";
