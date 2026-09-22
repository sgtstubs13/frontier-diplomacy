import React, {useEffect, useState} from "react";
import {createRoot} from "react-dom/client";
import "./style.css";

type Profile = {id: string; display_name: string; provider: string; model: string};
type Experiment = {experiment_id: string; status: {status: string}; budget: Record<string, string>; config: Record<string, unknown>};
const api = async (path: string, init?: RequestInit) => {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

function App() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [budget, setBudget] = useState("25");
  const [message, setMessage] = useState("");
  const refresh = async () => {
    const [p, e] = await Promise.all([api("/profiles"), api("/experiments")]);
    setProfiles(p.profiles); setExperiments(e.experiments);
  };
  useEffect(() => { refresh().catch(e => setMessage(String(e))); }, []);
  const toggle = (id: string) => setSelected(old => old.includes(id) ? old.filter(value => value !== id) : [...old, id]);
  const create = async () => {
    if (selected.length < 7) return setMessage("Select at least seven model profiles.");
    const payload = {name: "experiment", model_ids: selected, games: 7, seed: 42, max_year: 20,
      press_mode: "full_press", ending_mode: "draws_allowed", negotiation_rounds: 3,
      planning_phase: false, budget_usd: budget};
    try { const experiment = await api("/experiments", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)}); setMessage(`Created ${experiment.experiment_id}`); await refresh(); }
    catch (e) { setMessage(String(e)); }
  };
  return <main><header><h1>Frontier Diplomacy</h1><p>Local benchmark control room</p></header>
    <section><h2>New experiment</h2><p>Select competitors, then set the maximum amount this experiment may spend.</p>
      <div className="profiles">{profiles.map(profile => <label key={profile.id}><input type="checkbox" checked={selected.includes(profile.id)} onChange={() => toggle(profile.id)}/><b>{profile.display_name}</b><small>{profile.provider}: {profile.model}</small></label>)}</div>
      <label>USD budget <input type="number" min="0.01" step="0.01" value={budget} onChange={event => setBudget(event.target.value)}/></label>
      <button onClick={create}>Create experiment</button></section>
    <section><h2>Experiments</h2>{experiments.length === 0 ? <p>No experiments yet.</p> : <table><thead><tr><th>Experiment</th><th>Status</th><th>Spent</th><th>Reserved</th><th>Remaining</th></tr></thead><tbody>{experiments.map(exp => <tr key={exp.experiment_id}><td>{exp.experiment_id}</td><td>{exp.status.status}</td><td>${exp.budget.spent_usd}</td><td>${exp.budget.reserved_usd}</td><td>${exp.budget.remaining_usd}</td></tr>)}</tbody></table>}</section>
    {message && <aside>{message}</aside>}</main>;
}
createRoot(document.getElementById("root")!).render(<App/>);
