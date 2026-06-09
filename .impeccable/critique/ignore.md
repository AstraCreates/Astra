# Critique ignore list

Patterns below are accepted exceptions and will be silently dropped from future detector findings.

## layout-transition: SessionTour.tsx — .st-ring

The `.st-ring` CSS class transitions `top`, `left`, `width`, and `height` to reposition the tour spotlight ring over different target elements as the user advances through the onboarding tour. Width and height changes are load-bearing here (the ring must match the bounding box of each target element), and FLIP animation would require significant JS scaffolding for negligible gain on an infrequent overlay.
