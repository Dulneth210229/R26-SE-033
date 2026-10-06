// Classifies a security report's findings against the PREVIOUS version's findings into
// Resolved / Still Present / New / Ambiguous -- direct user request, prompted by a real report
// where a Coder Agent fix correctly resolved everything it was asked to fix, but the auto
// re-scan still showed 3 other, pre-existing findings the AI-deep-scan layer simply hadn't
// flagged in the earlier scan. Distinguishing "still broken" from "newly noticed" requires
// matching a finding across two scans -- this is that matching logic.
//
// Match key is deliberately (rule_id, file, cwe), NEVER line number: fixing one issue shifts
// every later line in the same file, confirmed directly against a real report pair where the
// exact same 3 findings recurred with shifted line numbers (16->14, 31->27, 52->42) between
// versions.
//
// `finding.id` (from the backend's SecurityFinding schema) is used ONLY to mark "already
// consumed" within one classification call -- it is NOT a stable cross-version identity. It
// bakes in the line number for deterministic-scanner findings (`f"{rule_id}:{rel}:{line}"`) or a
// scan-local sequential index for AI/LLM-review findings (`f"{rule_id}:{index}"`), so it can
// (and does) differ across versions for the identical underlying issue even when nothing else
// about it changed.

function findingKey(finding) {
  return `${finding.rule_id}|${finding.file}|${finding.cwe}`;
}

// Word-overlap similarity on `message` -- real signal for AI-deep-scan/LLM-review findings, whose
// message text is genuinely per-finding (built from that finding's own title/description). Zero
// discriminative power for deterministic-scanner findings sharing one rule, whose message is a
// per-RULE constant, not per-instance -- see the identical-messages fallback below for that case.
function messageSimilarity(a, b) {
  const wordsOf = (text) =>
    new Set(
      String(text || "")
        .toLowerCase()
        .split(/\W+/)
        .filter((w) => w.length > 3)
    );
  const wordsA = wordsOf(a);
  const wordsB = wordsOf(b);
  if (wordsA.size === 0 || wordsB.size === 0) return 0;
  let overlap = 0;
  for (const w of wordsA) {
    if (wordsB.has(w)) overlap += 1;
  }
  return overlap / Math.max(wordsA.size, wordsB.size);
}

// Pairs `previousBucket` findings against `currentBucket` findings (all sharing one findingKey).
// Returns { pairs: [{previous, current}], unmatchedPrevious, unmatchedCurrent }.
function pairWithinBucket(previousBucket, currentBucket) {
  if (previousBucket.length === 0 || currentBucket.length === 0) {
    return { pairs: [], unmatchedPrevious: previousBucket, unmatchedCurrent: currentBucket };
  }

  // Every message in the combined bucket is byte-identical -- the real, confirmed deterministic-
  // scanner collision case (e.g. every SEC-SECRET-GENERIC-KEY finding shares the same literal
  // rule message). Text similarity can't disambiguate here, so fall back to positional pairing
  // by ascending line number instead -- a fix rarely reorders the REMAINING same-rule findings in
  // a file, it just shifts their absolute lines.
  const allMessages = new Set([...previousBucket, ...currentBucket].map((f) => f.message));
  if (allMessages.size === 1) {
    const sortedPrev = [...previousBucket].sort((a, b) => (a.line ?? 0) - (b.line ?? 0));
    const sortedCurr = [...currentBucket].sort((a, b) => (a.line ?? 0) - (b.line ?? 0));
    const pairCount = Math.min(sortedPrev.length, sortedCurr.length);
    const pairs = [];
    for (let i = 0; i < pairCount; i += 1) {
      pairs.push({ previous: sortedPrev[i], current: sortedCurr[i] });
    }
    return {
      pairs,
      unmatchedPrevious: sortedPrev.slice(pairCount),
      unmatchedCurrent: sortedCurr.slice(pairCount),
    };
  }

  // Unambiguous 1:1 case -- exactly one candidate on each side, no need for similarity scoring.
  if (previousBucket.length === 1 && currentBucket.length === 1) {
    return { pairs: [{ previous: previousBucket[0], current: currentBucket[0] }], unmatchedPrevious: [], unmatchedCurrent: [] };
  }

  // General case: greedily pair by best message similarity, highest score first, never reusing a
  // side once matched. Anything left over after this is a genuine tie/ambiguity -- surfaced
  // explicitly rather than guessed (direct user decision).
  const remainingCurrent = [...currentBucket];
  const pairs = [];
  const unmatchedPrevious = [];
  for (const prev of previousBucket) {
    let bestIndex = -1;
    let bestScore = -1;
    remainingCurrent.forEach((curr, index) => {
      const score = messageSimilarity(prev.message, curr.message);
      if (score > bestScore) {
        bestScore = score;
        bestIndex = index;
      }
    });
    if (bestIndex !== -1 && bestScore > 0) {
      pairs.push({ previous: prev, current: remainingCurrent[bestIndex] });
      remainingCurrent.splice(bestIndex, 1);
    } else {
      unmatchedPrevious.push(prev);
    }
  }

  return { pairs, unmatchedPrevious, unmatchedCurrent: remainingCurrent };
}

export function classifySecurityFindings(previousFindings, currentFindings) {
  const previous = previousFindings || [];
  const current = currentFindings || [];

  const previousByKey = new Map();
  for (const finding of previous) {
    const key = findingKey(finding);
    if (!previousByKey.has(key)) previousByKey.set(key, []);
    previousByKey.get(key).push(finding);
  }
  const currentByKey = new Map();
  for (const finding of current) {
    const key = findingKey(finding);
    if (!currentByKey.has(key)) currentByKey.set(key, []);
    currentByKey.get(key).push(finding);
  }

  const resolved = [];
  const stillPresent = [];
  const introduced = [];
  const ambiguous = [];

  const allKeys = new Set([...previousByKey.keys(), ...currentByKey.keys()]);
  for (const key of allKeys) {
    const previousBucket = previousByKey.get(key) || [];
    const currentBucket = currentByKey.get(key) || [];
    const { pairs, unmatchedPrevious, unmatchedCurrent } = pairWithinBucket(previousBucket, currentBucket);

    for (const pair of pairs) {
      stillPresent.push(pair);
    }

    // A bucket that started with more than one candidate on both sides and still has leftovers
    // on both sides after pairing is a genuine, unresolvable tie -- not simply "some resolved,
    // some new". Surface those together as ambiguous instead of splitting them across the other
    // two buckets, which would silently assert a specific pairing this logic isn't confident in.
    if (unmatchedPrevious.length > 0 && unmatchedCurrent.length > 0) {
      ambiguous.push(...unmatchedPrevious, ...unmatchedCurrent);
    } else {
      resolved.push(...unmatchedPrevious);
      introduced.push(...unmatchedCurrent);
    }
  }

  return { resolved, stillPresent, introduced, ambiguous };
}
