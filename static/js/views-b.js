/* Views B: savings & investment, evaluation, contact & support */
(function (F) {
  const { $, $$, esc, fmt, vnd, pct, dur, api, toast, md, table, badge } = F;
  const V = F.views;
  const msgBox = (el, text, ok) => { el.innerHTML = text ? `<div class="msg ${ok ? 'ok' : 'err'}">${esc(text)}</div>` : ''; };

  /* ======================= SAVINGS & INVESTMENT ======================= */
  const goalHTML = (g, i) => `<div class="goal" data-i="${i}"><div class="flex" style="justify-content:space-between"><b>Goal ${i + 1}</b><button type="button" class="btn danger small rm" ${F.S.sv.goals.length <= 1 ? 'disabled' : ''}>Remove</button></div>
    <div class="form-grid" style="margin-top:10px"><div class="field"><label>Goal name</label><span class="ex">e.g. Buy a home / Emergency fund / Education</span><input type="text" class="g-name" value="${esc(g.name)}" maxlength="80"></div>
    ${F.moneyHTML('', { label: 'Target goal amount (VND)', value: g.target, example: '500,000,000 VND' }).replace('id=""', 'data-k="target"')}
    ${F.moneyHTML('', { label: 'Existing funds for this goal (VND)', value: g.current, example: '50,000,000 VND' }).replace('id=""', 'data-k="current"')}
    <div class="field"><label>Target timeframe (years)</label><span class="ex">e.g. 5 years</span><input type="number" class="g-years" min="1" max="50" step="1" value="${g.years}"></div>
    <div class="field"><label>Priority level</label><select class="g-prio">${['High', 'Medium', 'Low'].map((p) => `<option ${g.priority === p ? 'selected' : ''}>${p}</option>`).join('')}</select></div>
    <div class="field"><label>Specific constraints <span class="muted">(optional)</span></label><span class="ex">e.g. Must be liquid, no high-risk assets</span><input type="text" class="g-con" value="${esc(g.constraints || '')}" maxlength="200"></div></div></div>`;

  V.savings = async (root) => {
    const S = F.S;
    if (!S.sv) S.sv = { goals: null, chosen: null, assumptions: null, res: null };
    root.innerHTML = '<div class="pad"><span class="loader"></span> Loading…</div>';
    try { if (!S.sv.goals) S.sv.goals = (await api('/api/goals/defaults')).goals; }
    catch (e) { root.innerHTML = `<div class="pad"><h1 class="page-title">Savings &amp; Investment</h1><div class="notice warn">${esc(e.message)}</div><a class="btn" href="#/finance">Go to Financial Information</a></div>`; return; }
    root.innerHTML = `<div class="pad"><h1 class="page-title">Savings &amp; Investment</h1>
      <p class="page-sub">This page uses your saved financial information and assessment results to help you choose a priority goal, build an implementation plan and simulate options under current or hypothetical conditions.</p>
      <div class="sec" style="margin-top:0"><h2>1. Goal Input and Selection</h2>
        <div class="notice">Enter a savings or investment goal of your own, or use the goals recommended by the AI from your financial assessment. Amounts are in VND; thousands are separated by commas.</div>
        <div id="goals"></div><div class="row-actions" style="margin-top:6px"><button class="btn ghost small" id="aiGoals" type="button">✨ Use AI-recommended goals</button><button class="btn ghost small" id="addGoal" type="button">+ Add goal</button><button class="btn" id="analyze" type="button">Analyze goals →</button></div><div id="gm" style="margin-top:10px"></div></div>
      <div id="svResult"></div>
      <div class="sec"><h2>7. Additional Features</h2><div id="addl"></div></div>
      <div class="sec"><h2>Operating Principles</h2><div class="grid2"><div class="card"><h4>Python Engine</h4><p class="muted">Executes all deterministic financial and mathematical calculations.</p><h4>LLM Layer</h4><p class="muted">Assists in parsing goals, analyzing financial constraints, explaining trade-offs, and generating recommendations.</p>
        <h4>Security</h4><p class="muted">The Google AI Studio API key is stored in a server-side <code>.env</code> / environment variable and is never exposed to the browser.</p></div>
        <div class="card"><h4>The 4 LLM tasks</h4><ul><li><b>Task 1:</b> Parse &amp; validate input data / uploaded Excel file.</li><li><b>Task 2:</b> Reasoning &amp; prioritizing the 3 financial goals.</li><li><b>Task 3:</b> Trade-off &amp; risk explanation for What-if / stress-test scenarios.</li><li><b>Task 4:</b> RAG support chatbot.</li></ul>
        <h4>Guardrails &amp; Disclaimers</h4><p class="muted">The system states its assumptions, data limitations and risk factors, and never guarantees financial outcomes or investment yields.</p></div></div></div></div>`;
    F.bindMoney(root);

    const drawGoals = () => { $('#goals').innerHTML = S.sv.goals.map(goalHTML).join(''); F.bindMoney($('#goals')); $('#addGoal').disabled = S.sv.goals.length >= 5; };
    const readGoals = () => $$('.goal', root).map((el) => ({ name: $('.g-name', el).value.trim(), target: F.num($('[data-k=target]', el)), current: F.num($('[data-k=current]', el)),
      years: Math.min(Math.max(Number($('.g-years', el).value) || 1, 1), 50), priority: $('.g-prio', el).value, constraints: $('.g-con', el).value.trim() }));
    drawGoals();
    $('#goals').onclick = (e) => { const b = e.target.closest('.rm'); if (!b) return; S.sv.goals = readGoals(); S.sv.goals.splice(+b.closest('.goal').dataset.i, 1); S.sv.chosen = null; drawGoals(); };
    $('#addGoal').onclick = () => { S.sv.goals = readGoals(); S.sv.goals.push({ name: '', target: 0, current: 0, years: 5, priority: 'Medium', constraints: '' }); drawGoals(); };
    $('#aiGoals').onclick = async () => { try { S.sv.goals = (await api('/api/goals/defaults')).goals; S.sv.chosen = null; drawGoals(); toast('AI-recommended goals loaded'); } catch (e) { toast(e.message); } };
    const body = () => ({ goals: S.sv.goals, chosen: S.sv.chosen, assumptions: S.sv.assumptions });
    async function run(scroll) {
      S.sv.goals = readGoals();
      const bad = S.sv.goals.find((g) => !g.name || !g.target);
      if (!S.sv.goals.length || bad) return msgBox($('#gm'), 'Each goal needs a name and a target amount above 0.');
      msgBox($('#gm'), '');
      $('#svResult').innerHTML = '<div class="pad"><span class="loader"></span> Analyzing goals…</div>';
      try {
        const r = await api('/api/goals/analyze', { json: body() }); S.sv.res = r; render(r);
        if (scroll) $('#svResult').scrollIntoView({ behavior: 'smooth' });
        if (F.S.ai) api('/api/ai/explain', { json: { kind: 'goals', ...body() } }).then((x) => { if (x.source === 'gemini') { setNar('sv-rank', x.content.ranking); setNar('sv-primary', x.content.primary); setNar('sv-process', x.content.process); $$('.sv-tag').forEach((t) => (t.textContent = '✨ AI-generated explanation (Gemini) based on Python results')); } }).catch(() => {});
        if (r.secondary && F.S.ai) api('/api/ai/explain', { json: { kind: 'secondary', ...body() } }).then((x) => { if (x.source === 'gemini') setNar('sv-second', x.content.text); }).catch(() => {});
      } catch (e) { $('#svResult').innerHTML = ''; msgBox($('#gm'), e.message); }
    }
    const setNar = (id, t) => { const el = $('#' + id); if (el && t) el.innerHTML = md(t); };
    $('#analyze').onclick = () => run(true);

    function render(r) {
      const pb = r.plan_baseline, pa = r.plan_assumed, sec = r.secondary, a = r.assumed, base = r.baseline_capacity, g = r.goals[r.primary];
      const tag = '<span class="ai-tag sv-tag">🧮 Explanation generated from Python results</span>';
      const stat = (l, v) => `<div class="stat"><small>${l}</small><b>${v}</b></div>`;
      const planStats = (p) => `<div class="grid3">${stat('Additional total amount to accumulate', vnd(p.extra_needed))}${stat('Required monthly savings', vnd(p.required_monthly))}${stat('Expected time to goal at this savings rate', dur(p.months_at_rate))}${stat('Gap: savings capacity − required', (p.gap >= 0 ? '+' : '') + vnd(p.gap))}${stat(`Projected value at ${+p.years.toFixed(1)} years`, vnd(p.projected))}${stat('Estimated completion', pct(p.completion, 0))}</div>`;
      const opt = (p) => `<ul><li><b>Extend the timeframe:</b> ${p.options.extend_years == null ? 'not reachable within 50 years at this savings rate' : p.options.extend_years + ' year(s) at the current savings rate'}.</li><li><b>Adjust the target amount:</b> a target of ${vnd(p.options.reduced_target)} is reachable on the current schedule.</li><li><b>Adjust the savings rate:</b> save ${vnd(p.options.required_monthly)} per month to meet the original goal on time.</li></ul>`;
      const wi = a || { monthly_income: base.monthly_income, savings_rate: base.savings_rate, years: pb.years };
      const compCols = [['Primary goal · current baseline', pb, base.monthly_income]];
      if (pa) compCols.push(['Primary goal · future assumptions (hypothetical)', pa, a.monthly_income]);
      if (sec) { compCols.push(['Secondary goal · current baseline', sec.plan_baseline, base.monthly_income]); compCols.push(['Secondary goal · future assumptions (hypothetical)', sec.plan, a.monthly_income]); }
      const rows = [['Goal', (c) => esc(c[1].name)], ['Monthly income used', (c) => vnd(c[2])], ['Monthly savings', (c) => vnd(c[1].monthly_save)], ['Annual return (simulated)', (c) => pct(c[1].annual_return)], ['Timeframe', (c) => +c[1].years.toFixed(1) + ' yr'],
        ['Required monthly savings', (c) => vnd(c[1].required_monthly)], ['Time to goal', (c) => dur(c[1].months_at_rate)], ['Projected at deadline', (c) => vnd(c[1].projected)], ['Completion', (c) => pct(c[1].completion, 0)], ['Shortfall vs target', (c) => vnd(c[1].shortfall)]];
      $('#svResult').innerHTML = `
      <div class="sec"><h2>2. AI Goal Selection Based on Priorities</h2>${tag}
        <p class="muted">The AI weighs each goal against monthly available net cash flow (${vnd(base.net_cash_flow)}), usable savings and assets, debt obligations, liquidity needs, risk tolerance and each goal's timeframe and required amount.</p>
        ${r.ranking.map((x) => `<div class="rank-card${x.idx === r.primary ? ' first' : ''}"><div class="n">${x.rank}</div><div><b>${esc(x.name)}</b> ${x.idx === r.ai_pick ? badge('good', 'AI pick') : ''}<div class="muted" style="font-size:.88rem">Estimated completion ${pct(x.completion, 0)} · fit ${x.fit}% · needs ${vnd(x.required_monthly)}/month (${x.share_of_capacity == null ? 'n/a' : pct(x.share_of_capacity, 0)} of savings capacity)</div><div class="bar" style="margin-top:6px"><i style="width:${x.fit}%"></i></div>${x.notes.map((n) => `<div class="muted" style="font-size:.82rem">⚠ ${esc(n)}</div>`).join('')}</div>
          <div>${x.idx === r.primary ? badge('good', '✓ Selected') : `<button class="btn ghost small choose" data-i="${x.idx}">Choose this goal</button>`}</div></div>`).join('')}
        <div class="card" style="margin-top:14px"><h4>Why the AI recommends <i>${esc(r.ranking[0].name)}</i> — and what each goal means for you</h4><div id="sv-rank">${md(r.narrative.ranking)}</div><div id="sv-primary" style="margin-top:10px">${md(r.narrative.primary)}</div></div>
        <div class="notice"><b>Client autonomy:</b> you keep full authority. The AI does not decide for you—it only shows which goal best aligns with your financial position. Select any goal above to see its plan.</div></div>
      <div class="sec"><h2>3. Savings and Investment Plan — ${esc(g.name)}</h2>${planStats(pb)}<div class="card" style="margin-top:14px"><h4>Adjustment options</h4>${opt(pb)}</div>
        <div class="card" style="margin-top:14px"><h4>Step-by-step process</h4>${tag}<div id="sv-process">${md(r.narrative.process)}</div></div>
        <div class="notice warn">For investment components, yields are simulated assumptions only (base ${pct(base.annual_return)} per year for your risk level). The system highlights risk exposure and makes no return guarantees.</div></div>
      <div class="sec"><h2>4. What-If Goal Planning Tool</h2><p class="muted">Adjust the future assumptions for the selected goal, then press Recalculate. Future assumptions are displayed separately from your current baseline and are never actual realized income or returns.</p>
        <div class="card"><div class="form-grid"><div class="field"><div class="flex" style="justify-content:space-between"><label>Goal timeframe</label><b id="w1v"></b></div><input type="range" id="w1" min="1" max="50" step="1" value="${Math.round(wi.years)}"></div>
          ${F.moneyHTML('w2', { label: 'Assumed future monthly income (VND)', value: wi.monthly_income, example: '40,000,000 VND per month' })}
          <div class="field"><div class="flex" style="justify-content:space-between"><label>Monthly savings rate</label><b id="w3v"></b></div><input type="range" id="w3" min="0" max="100" step="1" value="${Math.round(wi.savings_rate * 100)}"></div>
          <div class="field"><label>Investment return assumption (change vs base yield)</label><span class="ex">e.g. − 3% to reflect losses, + 2% for growth</span><div class="wi-row" style="grid-template-columns:90px 1fr;border:0;padding:0"><select id="w4s"><option value="+">+</option><option value="-">−</option></select><div class="suffix"><input type="text" class="percent" inputmode="decimal" id="w4p" value="0"><span>%</span></div></div></div></div>
          <div class="row-actions" style="margin-top:0"><button class="btn" id="recalc">Recalculate</button><button class="btn ghost" id="clearA" type="button">Clear assumptions</button></div>
          ${a ? `<div class="notice warn"><b>Hypothetical assumptions in use:</b> income ${vnd(a.monthly_income)}, savings ${vnd(a.monthly_save)} per month (${pct(a.savings_rate, 0)} of income), yield ${pct(a.annual_return)}, ${+a.years.toFixed(1)} years.${a.exceeds_cash_flow > 0 ? ` This savings amount exceeds the assumed available cash flow by ${vnd(a.exceeds_cash_flow)}, so it would require cutting expenses.` : ''}</div>` : ''}</div>
        ${pa ? `<div style="margin-top:14px"><h4>Updated results (hypothetical)</h4>${planStats(pa)}<div class="card" style="margin-top:14px"><h4>Adjustment options</h4>${opt(pa)}</div></div>` : ''}</div>
      ${sec ? `<div class="sec"><h2>5. AI-Recommended Secondary Goal (hypothetical)</h2>${tag}<div class="card"><h3>${esc(sec.name)} ${sec.suggested ? badge('warn', 'AI-suggested') : ''}</h3><div id="sv-second">${md(r.narrative.secondary)}</div></div></div>` : '<div class="sec"><h2>5. AI-Recommended Secondary Goal</h2><div class="notice">Press Recalculate in the What-If tool above to receive a secondary goal matched to your assumed financial conditions.</div></div>'}
      <div class="sec"><h2>6. Summary Tables and Charts</h2>${table(['Metric'].concat(compCols.map((c) => c[0])), rows.map(([l, f]) => [l].concat(compCols.map(f))))}
        <div class="grid2" style="margin-top:16px"><div class="card"><h4>Projected wealth accumulation</h4><div class="chart-box"><canvas id="c1"></canvas></div></div><div class="card"><h4>Required monthly savings vs savings used</h4><div class="chart-box"><canvas id="c2"></canvas></div></div>
        <div class="card"><h4>Shortfall gap to target at deadline</h4><div class="chart-box"><canvas id="c3"></canvas></div></div><div class="card"><h4>Transparency: inputs &amp; assumptions</h4><ul><li>Monthly net cash flow (baseline): ${vnd(base.net_cash_flow)}</li><li>Savings used (baseline): ${vnd(base.monthly_save)} (${pct(base.savings_rate)} of income)</li><li>Base annual yield (${r.profile.risk} risk, simulated): ${pct(base.annual_return)}</li><li>Monthly compounding; deposits at month-end; no taxes or fees</li>${a ? `<li>Hypothetical yield: ${pct(a.annual_return)}; hypothetical income: ${vnd(a.monthly_income)}</li>` : ''}</ul></div></div></div>`;
      F.killCharts();
      const c = r.chart;
      F.makeChart('c1', 'line', c.labels, [{ label: 'Current baseline plan', data: c.baseline, borderColor: '#12a56a', backgroundColor: '#12a56a', tension: .25, pointRadius: 0 }].concat(c.assumed ? [{ label: 'Future assumptions (hypothetical)', data: c.assumed, borderColor: '#2b8de0', borderDash: [6, 4], tension: .25, pointRadius: 0 }] : []).concat([{ label: 'Target amount', data: c.target, borderColor: '#d64545', borderDash: [2, 4], pointRadius: 0 }]), { xTitle: 'Years' });
      const bl = ['Baseline'].concat(pa ? ['Hypothetical'] : []), req = [pb.required_monthly].concat(pa ? [pa.required_monthly] : []), use = [pb.monthly_save].concat(pa ? [pa.monthly_save] : []);
      F.makeChart('c2', 'bar', bl, [{ label: 'Required monthly savings', data: req, backgroundColor: '#f08a24' }, { label: 'Monthly savings used', data: use, backgroundColor: '#12a56a' }]);
      F.makeChart('c3', 'bar', bl, [{ label: 'Shortfall vs target', data: [pb.shortfall].concat(pa ? [pa.shortfall] : []), backgroundColor: '#d64545' }, { label: 'Surplus vs target', data: [pb.surplus].concat(pa ? [pa.surplus] : []), backgroundColor: '#2b8de0' }]);
      // what-if controls
      const sync = () => { $('#w1v').textContent = $('#w1').value + ' years'; $('#w3v').textContent = $('#w3').value + '%'; }; sync(); F.bindMoney($('#svResult'));
      $('#w1').oninput = sync; $('#w3').oninput = sync;
      $$('.choose', $('#svResult')).forEach((b) => (b.onclick = () => { S.sv.chosen = +b.dataset.i; S.sv.assumptions = null; run(false); }));
      $('#recalc').onclick = () => { S.sv.assumptions = { years: +$('#w1').value, income: F.num('w2'), save_rate: +$('#w3').value, ret_sign: $('#w4s').value, ret_pct: Number($('#w4p').value) || 0 }; run(false); };
      $('#clearA').onclick = () => { S.sv.assumptions = null; run(false); };
      addl();
    }

    async function addl() {
      let list = []; try { list = (await api('/api/plans')).plans; } catch (e) {}
      const sel = new Set();
      $('#addl').innerHTML = `<div class="row-actions" style="margin-top:0"><button class="btn" id="exPlan">⬇ Export Plan (.xlsx)</button><button class="btn ghost" id="again" type="button">🔄 Recalculate</button></div>
        <div class="card" style="margin-top:16px"><h4>Scenario management</h4><p class="muted">Save, edit or compare multiple planning options side by side.</p><div class="flex"><input type="text" id="pname" placeholder="Plan name, e.g. Home in 8 years" style="max-width:340px" maxlength="60"><button class="btn small" id="savePlan">Save current plan</button><button class="btn ghost small" id="cmp" disabled>Compare selected</button></div>
        <div id="plist" style="margin-top:14px">${list.length ? table(['Select', 'Name', 'Goal', 'Completion', 'Actions'], list.map((p) => [`<input type="checkbox" class="pick" data-id="${p.id}">`, esc(p.name) + (p.summary.hypothetical ? ' ' + badge('warn', 'hypothetical') : ''), esc(p.summary.goal), pct(p.summary.completion, 0), `<button class="btn ghost small ld" data-id="${p.id}">Edit</button> <button class="btn danger small dl" data-id="${p.id}">Delete</button>`])) : '<p class="muted">No saved plans yet.</p>'}</div><div id="cmpOut"></div></div>`;
      $('#exPlan').onclick = () => F.download('/api/export/plan', { json: body() }, 'finova_savings_investment_plan.xlsx').then(() => toast('Plan exported')).catch((e) => toast(e.message));
      $('#again').onclick = () => run(true);
      $('#savePlan').onclick = async () => { if (!S.sv.res) return toast('Analyze your goals first.'); try { await api('/api/plans', { json: { name: $('#pname').value, ...body() } }); toast('Plan saved'); addl(); } catch (e) { toast(e.message); } };
      $$('.pick').forEach((c) => (c.onchange = () => { c.checked ? sel.add(+c.dataset.id) : sel.delete(+c.dataset.id); $('#cmp').disabled = sel.size < 2; }));
      $$('.dl').forEach((b) => (b.onclick = async () => { await api('/api/plans/' + b.dataset.id, { method: 'DELETE' }); addl(); }));
      $$('.ld').forEach((b) => (b.onclick = () => { const p = list.find((x) => x.id === +b.dataset.id); S.sv.goals = p.goals; S.sv.chosen = p.chosen ?? null; S.sv.assumptions = p.assumptions || null; drawGoals(); run(true); }));
      $('#cmp').onclick = () => {
        const ps = list.filter((p) => sel.has(p.id)), f = [['Goal', (s) => esc(s.goal)], ['Target', (s) => vnd(s.target)], ['Timeframe', (s) => +s.years.toFixed(1) + ' yr'], ['Monthly savings', (s) => vnd(s.monthly_save)], ['Annual return (simulated)', (s) => pct(s.annual_return)], ['Required monthly', (s) => vnd(s.required_monthly)], ['Time to goal', (s) => dur(s.months)], ['Completion', (s) => pct(s.completion, 0)], ['Basis', (s) => (s.hypothetical ? 'Hypothetical assumptions' : 'Current baseline')]];
        $('#cmpOut').innerHTML = '<div style="margin-top:14px">' + table(['Metric'].concat(ps.map((p) => esc(p.name))), f.map(([l, fn]) => [l].concat(ps.map((p) => fn(p.summary))))) + '</div>';
      };
    }
    if (S.sv.res) { render(S.sv.res); }
  };

  /* ======================= EVALUATION ======================= */
  const CRIT = [
    ['accuracy', 'Accuracy', 'Evaluates the precision of financial calculations, simulation outcomes, and system-provided data.', ['Independent Benchmarking: cross-check FINOVA’s calculation outputs against independently calculated or verified standard mathematical results.', 'Financial Verification: verify the precision of cash flow values, financial ratios, and all five simulation scenarios.', 'Metric Tracking: record the number of correct versus incorrect cases and compute the overall accuracy rate (%).']],
    ['groundedness', 'Groundedness', 'Evaluates the extent to which AI insights, remarks, and recommendations strictly adhere to user-provided inputs, Python calculation outputs, and explicitly declared assumptions.', ['Input Integrity Check: verify that the AI utilizes correct and uncorrupted user input data.', 'Evidence Validation: ensure all generated conclusions are directly supported by corresponding calculation results and underlying assumptions.', 'Hallucination Detection: identify and eliminate self-derived information, unsupported figures, or conclusions that contradict the baseline data.']],
    ['usability', 'Usability', 'Evaluates the clarity, user-friendliness, and practical utility of the FINOVA interface.', ['Data Entry Experience: can users complete financial data entry effortlessly?', 'Visual Clarity: are summary tables, charts, and AI narrative insights intuitive and easy to interpret?', 'Recommendation Transparency: do users clearly understand the rationale behind AI-recommended savings or investment goals?', 'User Rating & Feedback: user satisfaction scores from 1 to 5 alongside qualitative feedback.']],
    ['processing', 'Processing Time', 'Evaluates system responsiveness and operational efficiency across pipeline steps.', ['Financial Analysis Latency: processing time for financial profile parsing and health checks.', 'Calculation Engine Speed: computational execution time for simulating all 5 financial scenarios.', 'AI Generation Time: latency for generating AI explanations and strategic recommendations.', 'Performance Metrics: average processing times, flagging slow execution edge cases.']]];
  const STAR_TXT = [['1 Star - Very Dissatisfied', 'Severely inaccurate results, difficult to use, or fails to meet needs.'], ['2 Stars - Dissatisfied', 'Contains many errors, unclear information, poor user experience.'], ['3 Stars - Neutral', 'Basic functions are usable, but improvement is still needed.'], ['4 Stars - Satisfied', 'Useful information, relatively clear results, easy-to-use interface; only a few minor points need improvement.'], ['5 Stars - Very Satisfied', 'Accurate results, transparent explanations, easy-to-use interface, and well-suited for financial planning needs.']];

  V.evaluation = async (root) => {
    root.innerHTML = '<div class="pad"><span class="loader"></span> Loading…</div>';
    let s = {}, mine = null; try { s = await api('/api/ratings'); mine = s.mine; } catch (e) {}
    root.innerHTML = `<div class="pad"><h1 class="page-title">Evaluation</h1><p class="page-sub">Evaluate FINOVA's performance and your experience on four criteria: Accuracy, Groundedness, Usability and Processing Time. Rate each from 1 to 5 stars, then confirm.</p>
      <details class="card" style="margin-bottom:18px"><summary style="cursor:pointer;font-weight:700">What do the stars mean?</summary><ul>${STAR_TXT.map(([a, b]) => `<li><b>${a}:</b> ${b}</li>`).join('')}</ul></details>
      <div class="card"><div id="em"></div>${CRIT.map(([k, t, d, items]) => `<div class="crit"><div><h3 style="margin:0">${CRIT.findIndex((c) => c[0] === k) + 1}. ${t}</h3><p class="muted" style="margin:.2em 0">${d}</p><ul>${items.map((i) => `<li>${i}</li>`).join('')}</ul></div>${F.stars('st-' + k, mine ? mine[k] : 0)}</div>`).join('')}
        <div class="field" style="margin-top:16px"><label for="cm">Comments <span class="muted">(optional)</span></label><textarea id="cm" rows="3" maxlength="1000" placeholder="Tell us what worked and what should improve">${esc(mine ? mine.comment || '' : '')}</textarea></div>
        <label class="flex" style="margin-bottom:14px"><input type="checkbox" id="fl" ${mine && mine.flagged ? 'checked' : ''}> Flag inaccurate results I noticed</label>
        <button class="btn" id="confirm">Confirm evaluation</button><div id="mine" style="margin-top:14px"></div></div>
      <div class="sec"><h2>Evaluation Summary Dashboard</h2><div id="dash"><span class="loader"></span></div>
        <div class="notice"><b>Note on methodology:</b> Accuracy, Groundedness and Processing Time are evaluated with specific, objective testing frameworks rather than subjective user feedback. Usability is assessed through structured user surveys combined with direct task-completion observation.</div></div>
      <div class="sec"><h2>Average rating from customers</h2><div id="avg"></div></div></div>`;
    F.bindStars(root);
    const showMine = (m) => { if (m) $('#mine').innerHTML = `<div class="notice">Your average: <b>${m.avg.toFixed(2)} / 5</b> (mean of the four criteria).</div>`; };
    const avgBox = (s) => ($('#avg').innerHTML = s.count ? `<div class="card" style="text-align:center">${F.starMeter(s.overall)}<div class="big" style="margin:8px 0">${s.overall.toFixed(1)}/5</div><p class="muted">Based on ${s.count} customer evaluation${s.count > 1 ? 's' : ''}${s.flagged ? ` · ${s.flagged} flagged inaccurate result${s.flagged > 1 ? 's' : ''}` : ''}</p>
        <div class="grid4">${CRIT.map(([k, t]) => `<div class="stat"><small>${t}</small><b>${(s.criteria[k] || 0).toFixed(2)}</b></div>`).join('')}</div></div>` : '<div class="card muted" style="text-align:center">No customer has rated FINOVA yet. Be the first to evaluate it above.</div>');
    showMine(mine); avgBox(s);
    $('#confirm').onclick = async () => {
      const v = Object.fromEntries(CRIT.map(([k]) => [k, +$('#st-' + k).dataset.value]));
      if (Object.values(v).some((x) => !x)) return msgBox($('#em'), 'Please rate all four criteria (1 to 5 stars each) before confirming.');
      try { const r = await api('/api/ratings', { json: { ...v, comment: F.val('cm'), flagged: $('#fl').checked } }); showMine(r.mine); avgBox(r); msgBox($('#em'), 'Thank you! Your evaluation was recorded.', true); loadDash(); $('#avg').scrollIntoView({ behavior: 'smooth' }); }
      catch (e) { msgBox($('#em'), e.message); }
    };
    async function loadDash() {
      try {
        const d = await api('/api/eval/dashboard');
        $('#dash').innerHTML = table(['Criterion', 'Measurement metric / KPI', 'Target benchmark', 'Actual result', 'Status'], d.rows.map((r) => [`<b>${r.criterion}</b>`, esc(r.kpi), esc(r.target), esc(r.actual), r.pass === null ? badge('na', 'Pending') : r.pass ? badge('good', 'Pass') : badge('bad', 'Fail')]));
        $$('#dash td.num').forEach((td) => (td.style.whiteSpace = 'normal'));
      } catch (e) { $('#dash').innerHTML = `<div class="msg err">${esc(e.message)}</div>`; }
    }
    loadDash();
  };

  /* ======================= CONTACT & SUPPORT ======================= */
  V.support = async (root) => {
    root.innerHTML = '<div class="pad"><span class="loader"></span></div>';
    if (!F.S.faq) F.S.faq = await api('/api/faq');
    const faq = F.S.faq, all = faq.topics.flatMap((t, ti) => t.questions.map((q, qi) => ({ ...q, topic: t.topic, ti, qi })));
    root.innerHTML = `<div class="pad"><h1 class="page-title">Contact &amp; Support</h1><p class="page-sub">Find answers, send a support request, or ask FINOVA's AI chatbot.</p>
      <div class="tabs" id="tabs"><button data-t="faq" class="on">1. FAQs</button><button data-t="ticket">2. Customer Support</button><button data-t="chat">3. AI Chatbot</button></div>
      <div id="t-faq"><div class="card"><p class="muted" style="margin-top:0">Look up guides and answers by topic: how to use FINOVA, entering financial information, interpreting evaluation results, and using savings and investment features.</p>
        <div class="field"><label>Search questions</label><div class="search-box"><input type="search" id="q" placeholder="Search questions…" autocomplete="off"><button type="button" class="arrow" id="arrow" aria-label="Show question types">▾</button><div class="suggest" id="sug"></div></div></div>
        <div class="form-grid"><div class="field"><label for="tp">Topics</label><select id="tp"><option value="">Select a topic…</option>${faq.topics.map((t, i) => `<option value="${i}">${esc(t.topic)}</option>`).join('')}</select></div>
          <div class="field"><label for="qs">Question</label><select id="qs" disabled><option value="">Select a question…</option></select></div></div><div id="ans"></div></div></div>
      <div id="t-ticket" hidden><div class="card"><p class="muted" style="margin-top:0">Submit support requests, report bugs, or contact the operations team. Choose the type of issue first.</p>
        <div class="grid2" id="types">${faq.support_types.map((t) => `<div class="type-card" data-l="${esc(t.label)}"><b>${esc(t.label)}</b><span>${esc(t.desc)}</span></div>`).join('')}</div>
        <form id="tf" novalidate hidden style="margin-top:22px"><div id="tm"></div><div class="form-grid"><div class="field"><label>Issue Type</label><input type="text" id="ty" readonly></div><div class="field"><label for="em">Email <span class="muted">(for our reply)</span></label><input type="email" id="em" value="${esc(F.S.user.email)}"></div></div>
          <div class="field"><label for="su">Subject</label><input type="text" id="su" maxlength="150" placeholder="Short title of your request"></div>
          <div class="field"><label for="de">Description</label><textarea id="de" rows="5" maxlength="4000" placeholder="Describe the problem in detail: what you did, what you expected and what happened"></textarea></div>
          <div class="field"><label for="at">Attachment <span class="muted">(optional screenshot of the error)</span></label><input type="file" id="at" accept="image/*"></div><button class="btn" type="submit">Submit Request</button></form></div></div>
      <div id="t-chat" hidden><div class="card"><p class="muted" style="margin-top:0">FINOVA AI explains how to use the platform, financial terms, evaluation results, simulation scenarios and savings or investment recommendations, using your calculated data.</p>
        ${F.S.ai ? '' : '<div class="notice warn">The AI model is not configured on this server, so the chatbot answers from the FINOVA documentation only.</div>'}
        <div class="chips">${['What is DTI and how is mine calculated?', 'Explain my five scenarios', 'How do I upload data from Excel?', 'How much should I save each month?'].map((x) => `<span class="chip">${x}</span>`).join('')}</div>
        <div class="chat"><div class="chat-log" id="log"><div class="bubble bot">Hi ${esc(F.S.user.name.split(' ')[0])}! I'm FINOVA AI. Ask me about using FINOVA, financial terms, or your results.</div></div><form class="chat-in" id="cf"><input type="text" id="ci" placeholder="Type your question…" maxlength="2000" autocomplete="off"><button class="btn small" type="submit">Send</button></form></div></div></div></div>`;
    $$('#tabs button').forEach((b) => (b.onclick = () => { $$('#tabs button').forEach((x) => x.classList.toggle('on', x === b)); ['faq', 'ticket', 'chat'].forEach((t) => ($('#t-' + t).hidden = t !== b.dataset.t)); }));
    // FAQ
    const sug = $('#sug'), showAns = (it) => { $('#ans').innerHTML = `<div class="faq-answer"><b>${esc(it.q)}</b><p style="margin:.5em 0 0">${esc(it.a)}</p></div>`; };
    const fillQ = (ti, qi) => { $('#tp').value = ti; const t = faq.topics[ti]; $('#qs').disabled = !t; $('#qs').innerHTML = '<option value="">Select a question…</option>' + (t ? t.questions.map((q, i) => `<option value="${i}">${esc(q.q)}</option>`).join('') : ''); if (qi != null) { $('#qs').value = qi; showAns(t.questions[qi]); } else $('#ans').innerHTML = ''; };
    $('#tp').onchange = () => fillQ($('#tp').value === '' ? null : +$('#tp').value);
    $('#qs').onchange = () => { if ($('#qs').value !== '') showAns(faq.topics[+$('#tp').value].questions[+$('#qs').value]); };
    $('#arrow').onclick = (e) => { e.stopPropagation(); sug.classList.toggle('open'); sug.innerHTML = faq.topics.map((t, i) => `<div data-topic="${i}"><b>${esc(t.topic)}</b><small>${t.questions.length} questions</small></div>`).join(''); };
    $('#q').oninput = () => { const v = $('#q').value.trim().toLowerCase(); if (!v) return sug.classList.remove('open'); const hits = all.filter((x) => (x.q + ' ' + x.topic).toLowerCase().includes(v)).slice(0, 8); sug.innerHTML = hits.length ? hits.map((x) => `<div data-ti="${x.ti}" data-qi="${x.qi}">${esc(x.q)}<small>${esc(x.topic)}</small></div>`).join('') : '<div class="muted">No matching questions</div>'; sug.classList.add('open'); };
    sug.onclick = (e) => { const d = e.target.closest('div[data-topic],div[data-ti]'); if (!d) return; if (d.dataset.topic != null) fillQ(+d.dataset.topic); else { fillQ(+d.dataset.ti, +d.dataset.qi); $('#q').value = ''; } sug.classList.remove('open'); };
    document.addEventListener('click', (e) => { if (!e.target.closest('.search-box')) sug.classList.remove('open'); });
    // tickets
    $$('.type-card').forEach((c) => (c.onclick = () => { $$('.type-card').forEach((x) => x.classList.toggle('on', x === c)); $('#tf').hidden = false; $('#ty').value = c.dataset.l; $('#su').focus(); }));
    $('#tf').onsubmit = async (e) => {
      e.preventDefault(); const fd = new FormData(); fd.append('type', F.val('ty')); fd.append('subject', F.val('su')); fd.append('description', F.val('de')); fd.append('email', F.val('em')); if ($('#at').files[0]) fd.append('attachment', $('#at').files[0]);
      try { const r = await api('/api/support', { method: 'POST', body: fd }); msgBox($('#tm'), `Request submitted. Your ticket number is ${r.ticket}. We will reply by email.`, true); $('#su').value = ''; $('#de').value = ''; $('#at').value = ''; }
      catch (er) { msgBox($('#tm'), er.message); }
    };
    // chat
    const hist = [], log = $('#log');
    const bubble = (t, who) => { const d = document.createElement('div'); d.className = 'bubble ' + who; d.innerHTML = who === 'bot' ? md(t) : esc(t); log.appendChild(d); log.scrollTop = log.scrollHeight; return d; };
    async function send(text) {
      if (!text) return; bubble(text, 'me'); const w = bubble('…', 'bot');
      try { const r = await api('/api/chat', { json: { message: text, history: hist } }); w.innerHTML = md(r.reply); hist.push({ role: 'user', text }, { role: 'assistant', text: r.reply }); }
      catch (e) { w.textContent = e.message; } log.scrollTop = log.scrollHeight;
    }
    $('#cf').onsubmit = (e) => { e.preventDefault(); const t = $('#ci').value.trim(); $('#ci').value = ''; send(t); };
    $$('.chip').forEach((c) => (c.onclick = () => send(c.textContent)));
  };
})(window.FIN);
