#!/usr/bin/env node
/**
 * PostToolUse guard for SJTU-TPMSHX.
 *
 * When an Edit/Write touches a file that carries a hard numerical invariant,
 * inject a reminder of THAT file's invariant + the verification gate, so the
 * invariant is re-surfaced at the moment of editing even if the agent's context
 * has compacted. Non-blocking advisory — never fails the tool call.
 *
 * Wired via .claude/settings.json (PostToolUse, matcher Edit|Write|MultiEdit).
 */
'use strict';

let raw = '';
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  let data = {};
  try { data = JSON.parse(raw || '{}'); } catch (_) { /* malformed → no-op */ }

  const ti = data.tool_input || {};
  const fp = String(ti.file_path || ti.path || '').replace(/\\/g, '/');

  // file-pattern → the invariant to re-surface
  const RULES = [
    [/solvers\/(ltne_energy(_3d)?|_kernels_ltne_3d)\.py$/,
      'ε is split in ONE place (ltne_energy halves total ε → ε/2). Callers pass FULL ε. ' +
      'Asymmetric ε_A≠ε_B (offset δ) is the ONLY exception — split upstream, summing to ε, ' +
      'passed via the eps_A/eps_B hooks; the kernel does NOT re-halve. Do not pre-divide ε.'],
    [/solvers\/asym_split\.py$/,
      'asym_split is the SINGLE source of the geometry split ratio (ε_A/ε_B from offset δ), ' +
      'shared by stages_2d AND stages_3d. Sides must sum to the full ε; δ=0 must stay ' +
      'bit-identical to the symmetric ε/2 baseline.'],
    [/solvers\/(simple_solver(_3d)?|_kernels_simple_(2d|3d))\.py$/,
      'Mass-flux inlet is the air-inlet default (massflux_inlet=True) in BOTH 2D and 3D — ' +
      'do not revert to a fixed-velocity inlet (grid-dependent Δp). Kernel velocities are ' +
      'INTERSTITIAL throughout; a superficial velocity here is a bug. Since M2 (2026-07-09, ' +
      'ledger B5) the 2D momentum kernels carry ε ONLY as face ratios r=ε_f/ε_CV on F and D ' +
      '(ε-divided VANS; pressure term unfactored, DF drag untouched) — uniform ε must stay ' +
      'bit-identical (r≡1.0), so never introduce an ABSOLUTE ε into momentum. 3D momentum ' +
      'is deliberately unweighted (trigger-bound follow-up, see B5).'],
    [/solvers\/envelope\.py$/,
      'The compressible validity envelope guards choke/supersonic. NEVER "fix" a ' +
      'ChokedFlowError by removing the guard, widening the P_abs clip, or returning a ' +
      'number — change the operating point (lower v, shorter L, higher P_in).'],
    [/solvers\/nu_correlations\.py$/,
      'Nu coefficients have a SINGLE source (NU_COEFFS / WATER_NU_COEFFS / nu_sco2_topo). ' +
      'Never duplicate or inline Nu coefficients elsewhere.'],
    [/df_surrogate\/(predict|gamma_df)\.py$/,
      'The DF closure already bakes in SLM surface roughness (default backend gamma_df: ' +
      'cF = cF_smooth x experiment-anchored gamma). Never add a friction/roughness ' +
      'multiplier on top — it double-counts.'],
    [/domain\/compute_config\.py$/,   // moved from controllers/ in the 2026-07-02 contracts layer
      'Compressible is required: variable_rho_cp=True / fluid_type=ideal_gas is the default. ' +
      'Never substitute isothermal as a "simplification".'],
  ];

  for (const [re, inv] of RULES) {
    if (re.test(fp)) {
      const msg =
        `[invariant-guard] Edited a hard-invariant file (${fp}).\n` +
        `Invariant: ${inv}\n` +
        `Before claiming done: run /check (full pytest) and confirm the golden gate is ` +
        `bit-identical (or an intentional, stated re-baseline).`;
      process.stdout.write(JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PostToolUse',
          additionalContext: msg,
        },
      }));
      break;
    }
  }
  process.exit(0);
});
