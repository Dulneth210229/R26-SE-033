"""
Single source of truth for the set of UML combined-fragment "opener" kinds the sequence diagram
pipeline supports, plus the full set of valid interaction kinds overall.

Purpose: `sequence_modeler.py`, `sequence_builder.py`, and `sequence_validator.py` each used to
hardcode their own independent copy of "which fragment kinds exist" -- a real, confirmed
inconsistency: an unrecognized kind was silently DROPPED by the modeler/builder (no error, no
log) but would be REJECTED by the validator ("Invalid sequence interaction kind") if it ever
reached that stage. Adding a new fragment kind (e.g. `par_start` for parallel/concurrent
behavior, `break_start` for an early-exit alternative) previously meant remembering to update
three separately-hardcoded sets in sync. Importing from this one module instead makes that class
of drift structurally impossible.

Deliberately a standalone module with zero imports from the other three files -- none of them
import each other today, and this keeps it that way (no directional coupling implied between
modeler/builder/validator over what is really just shared vocabulary, not owned logic).
"""

from __future__ import annotations

# Every fragment kind that OPENS a UML combined fragment block, paired with a later "end". Each
# entry corresponds to a real, standard UML interaction operator:
# - alt_start: alternatives (if/else branching) -- pairs with an optional "else".
# - opt_start: an optional fragment (a single branch that may or may not execute).
# - loop_start: a genuinely repeated action (iterating a list, retrying, polling).
# - par_start: genuinely CONCURRENT/simultaneous behavior -- never sequential steps.
# - break_start: an alternative that, when triggered, ends the WHOLE enclosing interaction (e.g.
#   an early-exit validation failure) -- distinct from alt/opt, which only skip within themselves.
FRAGMENT_OPENER_KINDS = {"alt_start", "opt_start", "loop_start", "par_start", "break_start"}

# Every valid `interactions[].kind` value: the fragment openers above, plus "else" (only valid
# immediately inside an alt_start...end block), "end" (closes the innermost open fragment), and
# "message" (a plain lifeline-to-lifeline call, the default/most common kind).
ALL_INTERACTION_KINDS = FRAGMENT_OPENER_KINDS | {"else", "end", "message"}
