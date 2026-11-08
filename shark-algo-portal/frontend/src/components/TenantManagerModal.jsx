import React, { useState, useEffect } from 'react';
import { 
  Users, Key, Shield, ShieldCheck, PlusCircle, CheckCircle2, 
  AlertCircle, X, Sliders, RefreshCw, Play, Pause, Square, ExternalLink, Lock 
} from 'lucide-react';

export default function TenantManagerModal({ 
  isOpen, 
  onClose, 
  activeTenantId, 
  onSelectTenant 
}) {
  const [activeTab, setActiveTab] = useState('accounts'); // 'accounts' | 'onboard'
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  // Key Modal Sub-state
  const [keyModalTenant, setKeyModalTenant] = useState(null);
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [apiSecretInput, setApiSecretInput] = useState('');
  const [keyNickname, setKeyNickname] = useState('Primary API Key');
  const [isSavingKeys, setIsSavingKeys] = useState(false);

  // Config Modal Sub-state
  const [configModalTenant, setConfigModalTenant] = useState(null);
  const [editCapital, setEditCapital] = useState(100);
  const [editRiskPct, setEditRiskPct] = useState(1.0);
  const [editDailyLoss, setEditDailyLoss] = useState(3.0);
  const [editSizingMode, setEditSizingMode] = useState('AUTO');
  const [editManualLots, setEditManualLots] = useState(0.001);
  const [editMode, setEditMode] = useState('PAPER');
  const [isSavingConfig, setIsSavingConfig] = useState(false);

  // Onboarding Form State
  const [newEmail, setNewEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newCapital, setNewCapital] = useState(500);
  const [newRiskPct, setNewRiskPct] = useState(1.0);
  const [newMode, setNewMode] = useState('PAPER');
  const [newRole, setNewRole] = useState('CLIENT');
  const [isRegistering, setIsRegistering] = useState(false);

  // Fetch tenants
  const fetchTenants = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/tenants');
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to fetch tenants');
      setTenants(data.tenants || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchTenants();
    }
  }, [isOpen]);

  // Handle Tenant Onboarding
  const handleRegister = async (e) => {
    e.preventDefault();
    if (!newEmail || !newPassword) {
      alert('Email and temporary password are required.');
      return;
    }
    setIsRegistering(true);
    setError(null);
    try {
      const res = await fetch('/api/tenants/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: newEmail.trim(),
          password: newPassword,
          capital_base: parseFloat(newCapital) || 100.0,
          risk_per_trade_pct: parseFloat(newRiskPct) || 1.0,
          mode: newMode,
          role: newRole,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Registration failed');

      setSuccessMsg(`✅ Successfully onboarded client ${newEmail}!`);
      setNewEmail('');
      setNewPassword('');
      setActiveTab('accounts');
      fetchTenants();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsRegistering(false);
    }
  };

  // Handle Save API Keys
  const handleSaveKeys = async (e) => {
    e.preventDefault();
    if (!keyModalTenant) return;
    setIsSavingKeys(true);
    try {
      const res = await fetch(`/api/tenants/${keyModalTenant.id}/keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_key: apiKeyInput.trim(),
          api_secret: apiSecretInput.trim(),
          nickname: keyNickname.trim() || 'Default API Key',
          exchange: 'SHARK',
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to save API keys');

      setSuccessMsg(`🔐 AES-256 encrypted keys stored for ${keyModalTenant.email}`);
      setKeyModalTenant(null);
      setApiKeyInput('');
      setApiSecretInput('');
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err) {
      alert('Key save error: ' + err.message);
    } finally {
      setIsSavingKeys(false);
    }
  };

  // Handle Save Config
  const handleSaveConfig = async (e) => {
    e.preventDefault();
    if (!configModalTenant) return;
    setIsSavingConfig(true);
    try {
      const res = await fetch(`/api/tenants/${configModalTenant.id}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          capital_base: parseFloat(editCapital),
          risk_per_trade_pct: parseFloat(editRiskPct),
          daily_loss_limit_pct: parseFloat(editDailyLoss),
          sizing_mode: editSizingMode,
          manual_lot_size: parseFloat(editManualLots),
          mode: editMode,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to update config');

      setSuccessMsg(`⚙️ Configuration updated for ${configModalTenant.email}`);
      setConfigModalTenant(null);
      fetchTenants();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err) {
      alert('Config update error: ' + err.message);
    } finally {
      setIsSavingConfig(false);
    }
  };

  // Toggle active/pause state
  const handleToggleActive = async (tenant) => {
    const nextState = tenant.is_active ? 0 : 1;
    try {
      const res = await fetch(`/api/tenants/${tenant.id}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: nextState }),
      });
      if (res.ok) {
        fetchTenants();
      }
    } catch (err) {
      alert('Failed to update tenant status: ' + err.message);
    }
  };

  // Close position for tenant
  const handleClosePosition = async (tenant) => {
    if (!window.confirm(`Close active open position strictly for ${tenant.email}?`)) return;
    try {
      const res = await fetch(`/api/tenants/${tenant.id}/close`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Close failed');
      alert(`✅ Position closed for ${tenant.email}`);
    } catch (err) {
      alert('Close error: ' + err.message);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-[#0c111d] border border-[#1d273b] rounded-2xl w-full max-w-5xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden font-sans">
        
        {/* Top Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#182338] bg-[#090d16]">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-[#00e5ff]/10 border border-[#00e5ff]/30 flex items-center justify-center text-[#00e5ff]">
              <Users className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h2 className="text-base font-bold text-white tracking-wide">
                  Multi-Tenant Client & Account Cockpit
                </h2>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#00e5ff]/20 text-[#00e5ff] font-bold border border-[#00e5ff]/30">
                  MASTER DISPATCHER
                </span>
              </div>
              <p className="text-xs text-slate-400 font-mono">
                Isolated risk sandboxes • AES-256 Vault • $O(1)$ Master Broadcaster
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <button
              onClick={fetchTenants}
              disabled={loading}
              className="p-1.5 rounded-lg bg-[#141d2e] hover:bg-[#1a263d] text-slate-300 transition text-xs flex items-center space-x-1 cursor-pointer"
              title="Refresh Tenants"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-[#00e5ff]' : ''}`} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg bg-[#141d2e] hover:bg-[#1a263d] text-slate-400 hover:text-white transition cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Success / Error Alerts */}
        {successMsg && (
          <div className="mx-6 mt-4 p-3 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs flex items-center space-x-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{successMsg}</span>
          </div>
        )}
        {error && (
          <div className="mx-6 mt-4 p-3 rounded-lg bg-rose-500/15 border border-rose-500/30 text-rose-300 text-xs flex items-center space-x-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Tab Navigation */}
        <div className="flex border-b border-[#182338] px-6 bg-[#090d16]">
          <button
            onClick={() => setActiveTab('accounts')}
            className={`py-3 px-4 text-xs font-mono font-bold border-b-2 transition flex items-center space-x-2 cursor-pointer ${
              activeTab === 'accounts'
                ? 'border-[#00e5ff] text-[#00e5ff]'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            <span>Client Accounts ({tenants.length})</span>
          </button>
          <button
            onClick={() => setActiveTab('onboard')}
            className={`py-3 px-4 text-xs font-mono font-bold border-b-2 transition flex items-center space-x-2 cursor-pointer ${
              activeTab === 'onboard'
                ? 'border-[#00e5ff] text-[#00e5ff]'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <PlusCircle className="w-3.5 h-3.5" />
            <span>+ Onboard New Client</span>
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {activeTab === 'accounts' ? (
            <div className="space-y-4">
              {tenants.length === 0 ? (
                <div className="text-center py-12 text-slate-500 font-mono text-xs">
                  {loading ? 'Loading tenant database...' : 'No tenant accounts registered yet.'}
                </div>
              ) : (
                <div className="overflow-x-auto border border-[#1b253a] rounded-xl bg-[#090d16]">
                  <table className="w-full text-left text-xs font-mono border-collapse">
                    <thead>
                      <tr className="border-b border-[#1b253a] bg-[#0c121f] text-slate-400 text-[11px] uppercase tracking-wider">
                        <th className="py-3 px-4">Account / Email</th>
                        <th className="py-3 px-4">Role</th>
                        <th className="py-3 px-4">Mode</th>
                        <th className="py-3 px-4">Capital Base</th>
                        <th className="py-3 px-4">Risk Budget</th>
                        <th className="py-3 px-4">Sizing</th>
                        <th className="py-3 px-4">Status</th>
                        <th className="py-3 px-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#151e31]">
                      {tenants.map((t) => {
                        const isCurrentActive = activeTenantId === t.id;
                        return (
                          <tr 
                            key={t.id} 
                            className={`transition hover:bg-[#0f1729] ${isCurrentActive ? 'bg-[#00e5ff]/5' : ''}`}
                          >
                            <td className="py-3 px-4">
                              <div className="flex flex-col">
                                <span className="font-bold text-white flex items-center space-x-1.5">
                                  <span>{t.email}</span>
                                  {isCurrentActive && (
                                    <span className="text-[9px] px-1.5 py-0.2 rounded bg-[#00e5ff]/20 text-[#00e5ff] border border-[#00e5ff]/40">
                                      VIEWING
                                    </span>
                                  )}
                                </span>
                                <span className="text-[10px] text-slate-500">{t.id}</span>
                              </div>
                            </td>
                            <td className="py-3 px-4">
                              <span className={`text-[10px] px-2 py-0.5 rounded font-bold ${
                                t.role === 'SUPERADMIN' 
                                  ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                                  : 'bg-slate-800 text-slate-300 border border-slate-700'
                              }`}>
                                {t.role}
                              </span>
                            </td>
                            <td className="py-3 px-4">
                              <span className={`text-[10px] px-2 py-0.5 rounded font-bold ${
                                t.mode === 'LIVE'
                                  ? 'bg-rose-500/20 text-rose-400 border border-rose-500/40'
                                  : 'bg-amber-400/20 text-amber-300 border border-amber-400/30'
                              }`}>
                                {t.mode}
                              </span>
                            </td>
                            <td className="py-3 px-4 font-bold text-white">
                              ${parseFloat(t.capital_base || 100).toFixed(2)}
                            </td>
                            <td className="py-3 px-4 text-slate-300">
                              {parseFloat(t.risk_per_trade_pct || 1.0).toFixed(1)}% / trade
                            </td>
                            <td className="py-3 px-4 text-slate-300">
                              <span className="text-slate-400 text-[10px]">
                                {t.sizing_mode} {t.sizing_mode === 'MANUAL' ? `(${t.manual_lot_size} lots)` : ''}
                              </span>
                            </td>
                            <td className="py-3 px-4">
                              <button
                                onClick={() => handleToggleActive(t)}
                                className={`text-[10px] px-2 py-0.5 rounded font-bold flex items-center space-x-1 cursor-pointer transition ${
                                  t.is_active
                                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30'
                                    : 'bg-slate-700/50 text-slate-400 border border-slate-600 hover:bg-slate-700'
                                }`}
                                title="Click to toggle Active/Paused"
                              >
                                <span className={`w-1.5 h-1.5 rounded-full ${t.is_active ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`} />
                                <span>{t.is_active ? 'ACTIVE' : 'PAUSED'}</span>
                              </button>
                            </td>
                            <td className="py-3 px-4 text-right">
                              <div className="flex items-center justify-end space-x-1.5">
                                {/* Inspect Dashboard Button */}
                                <button
                                  onClick={() => {
                                    onSelectTenant(t.id);
                                    onClose();
                                  }}
                                  className="px-2 py-1 rounded bg-[#16233a] hover:bg-[#203254] text-[#00e5ff] text-[11px] font-bold transition flex items-center space-x-1 cursor-pointer"
                                  title="Switch Terminal view to this tenant"
                                >
                                  <ExternalLink className="w-3 h-3" />
                                  <span>View</span>
                                </button>

                                {/* API Key Vault Button */}
                                <button
                                  onClick={() => {
                                    setKeyModalTenant(t);
                                    setApiKeyInput('');
                                    setApiSecretInput('');
                                  }}
                                  className="p-1 rounded bg-[#16233a] hover:bg-[#203254] text-amber-400 transition cursor-pointer"
                                  title="Enter Exchange API Keys (AES-256 Vault)"
                                >
                                  <Key className="w-3.5 h-3.5" />
                                </button>

                                {/* Config Risk Limits Button */}
                                <button
                                  onClick={() => {
                                    setConfigModalTenant(t);
                                    setEditCapital(t.capital_base || 100);
                                    setEditRiskPct(t.risk_per_trade_pct || 1.0);
                                    setEditDailyLoss(t.daily_loss_limit_pct || 3.0);
                                    setEditSizingMode(t.sizing_mode || 'AUTO');
                                    setEditManualLots(t.manual_lot_size || 0.001);
                                    setEditMode(t.mode || 'PAPER');
                                  }}
                                  className="p-1 rounded bg-[#16233a] hover:bg-[#203254] text-slate-300 transition cursor-pointer"
                                  title="Configure Risk & Sizing Envelope"
                                >
                                  <Sliders className="w-3.5 h-3.5" />
                                </button>

                                {/* Manual Close Button */}
                                <button
                                  onClick={() => handleClosePosition(t)}
                                  className="p-1 rounded bg-rose-950/40 hover:bg-rose-900/60 text-rose-400 border border-rose-800/40 transition cursor-pointer"
                                  title="Emergency Close position for this tenant"
                                >
                                  <Square className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ) : (
            /* Onboarding Form Tab */
            <form onSubmit={handleRegister} className="max-w-2xl mx-auto space-y-4">
              <div className="bg-[#090d16] border border-[#1b253a] p-4 rounded-xl space-y-3">
                <div className="flex items-center space-x-2 text-white font-bold text-xs pb-2 border-b border-[#182338]">
                  <PlusCircle className="w-4 h-4 text-[#00e5ff]" />
                  <span>Client Account Details</span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-mono text-slate-400 mb-1">Client Email Address</label>
                    <input
                      type="email"
                      required
                      placeholder="client@investor.com"
                      value={newEmail}
                      onChange={(e) => setNewEmail(e.target.value)}
                      className="w-full bg-[#0c121e] border border-[#1e2a42] rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-[#00e5ff]"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-mono text-slate-400 mb-1">Temporary Password</label>
                    <input
                      type="password"
                      required
                      placeholder="••••••••••••"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      className="w-full bg-[#0c121e] border border-[#1e2a42] rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-[#00e5ff]"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
                  <div>
                    <label className="block text-[11px] font-mono text-slate-400 mb-1">Allocated Capital ($)</label>
                    <input
                      type="number"
                      step="1"
                      min="10"
                      value={newCapital}
                      onChange={(e) => setNewCapital(e.target.value)}
                      className="w-full bg-[#0c121e] border border-[#1e2a42] rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-[#00e5ff]"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-mono text-slate-400 mb-1">Risk per Trade (%)</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0.1"
                      max="10.0"
                      value={newRiskPct}
                      onChange={(e) => setNewRiskPct(e.target.value)}
                      className="w-full bg-[#0c121e] border border-[#1e2a42] rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-[#00e5ff]"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-mono text-slate-400 mb-1">Trading Mode</label>
                    <select
                      value={newMode}
                      onChange={(e) => setNewMode(e.target.value)}
                      className="w-full bg-[#0c121e] border border-[#1e2a42] rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-[#00e5ff]"
                    >
                      <option value="PAPER">PAPER (Simulation)</option>
                      <option value="LIVE">LIVE (Exchange Orders)</option>
                    </select>
                  </div>
                </div>
              </div>

              <div className="flex justify-end pt-2">
                <button
                  type="submit"
                  disabled={isRegistering}
                  className="px-5 py-2.5 rounded-xl bg-[#00e5ff] hover:bg-[#33ebff] text-[#080b11] font-bold font-mono text-xs transition cursor-pointer shadow-lg shadow-[#00e5ff]/20 disabled:opacity-50"
                >
                  {isRegistering ? 'Provisioning Pod...' : '🚀 Deploy Isolated Worker Pod'}
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Sub-Modal: AES-256 Key Vault */}
        {keyModalTenant && (
          <div className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm">
            <div className="bg-[#0c121e] border border-amber-500/40 rounded-xl p-6 w-full max-w-md space-y-4 shadow-2xl">
              <div className="flex items-center justify-between pb-2 border-b border-[#1b253a]">
                <div className="flex items-center space-x-2 text-amber-400">
                  <Key className="w-4 h-4" />
                  <h3 className="font-bold text-sm">AES-256 Vault: {keyModalTenant.email}</h3>
                </div>
                <button onClick={() => setKeyModalTenant(null)} className="text-slate-400 hover:text-white">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <p className="text-[11px] font-mono text-slate-400">
                Credentials are encrypted using Fernet AES-256 at rest. The Master Engine decrypts keys strictly Just-In-Time (JIT) in RAM when placing orders.
              </p>

              <form onSubmit={handleSaveKeys} className="space-y-3 font-mono text-xs">
                <div>
                  <label className="block text-slate-400 mb-1">Exchange API Key</label>
                  <input
                    type="password"
                    required
                    placeholder="Shark Exchange API Key"
                    value={apiKeyInput}
                    onChange={(e) => setApiKeyInput(e.target.value)}
                    className="w-full bg-[#080d16] border border-[#1e2a42] rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-400"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Exchange API Secret</label>
                  <input
                    type="password"
                    required
                    placeholder="Shark Exchange API Secret"
                    value={apiSecretInput}
                    onChange={(e) => setApiSecretInput(e.target.value)}
                    className="w-full bg-[#080d16] border border-[#1e2a42] rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-400"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1">Key Nickname (Optional)</label>
                  <input
                    type="text"
                    value={keyNickname}
                    onChange={(e) => setKeyNickname(e.target.value)}
                    className="w-full bg-[#080d16] border border-[#1e2a42] rounded-lg px-3 py-2 text-white focus:outline-none focus:border-amber-400"
                  />
                </div>

                <div className="flex justify-end space-x-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setKeyModalTenant(null)}
                    className="px-3 py-2 rounded-lg bg-[#151f33] text-slate-300 hover:text-white text-xs cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSavingKeys}
                    className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-black font-bold text-xs transition cursor-pointer shadow-lg shadow-amber-500/20 disabled:opacity-50"
                  >
                    {isSavingKeys ? 'Encrypting...' : '🔒 Encrypt & Save to Vault'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Sub-Modal: Risk Configuration Envelope */}
        {configModalTenant && (
          <div className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm">
            <div className="bg-[#0c121e] border border-[#1b253a] rounded-xl p-6 w-full max-w-md space-y-4 shadow-2xl">
              <div className="flex items-center justify-between pb-2 border-b border-[#1b253a]">
                <div className="flex items-center space-x-2 text-[#00e5ff]">
                  <Sliders className="w-4 h-4" />
                  <h3 className="font-bold text-sm">Risk Sandbox: {configModalTenant.email}</h3>
                </div>
                <button onClick={() => setConfigModalTenant(null)} className="text-slate-400 hover:text-white">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <form onSubmit={handleSaveConfig} className="space-y-3 font-mono text-xs">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-slate-400 mb-1">Capital Base ($)</label>
                    <input
                      type="number"
                      step="1"
                      min="10"
                      value={editCapital}
                      onChange={(e) => setEditCapital(e.target.value)}
                      className="w-full bg-[#080d16] border border-[#1e2a42] rounded-lg px-3 py-2 text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-slate-400 mb-1">Risk per Trade (%)</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0.1"
                      max="10.0"
                      value={editRiskPct}
                      onChange={(e) => setEditRiskPct(e.target.value)}
                      className="w-full bg-[#080d16] border border-[#1e2a42] rounded-lg px-3 py-2 text-white"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-slate-400 mb-1">Daily Loss Cap (%)</label>
                    <input
                      type="number"
                      step="0.5"
                      min="1.0"
                      max="20.0"
                      value={editDailyLoss}
                      onChange={(e) => setEditDailyLoss(e.target.value)}
                      className="w-full bg-[#080d16] border border-[#1e2a42] rounded-lg px-3 py-2 text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-slate-400 mb-1">Trading Mode</label>
                    <select
                      value={editMode}
                      onChange={(e) => setEditMode(e.target.value)}
                      className="w-full bg-[#080d16] border border-[#1e2a42] rounded-lg px-3 py-2 text-white"
                    >
                      <option value="PAPER">PAPER</option>
                      <option value="LIVE">LIVE</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-slate-400 mb-1">Sizing Mode</label>
                    <select
                      value={editSizingMode}
                      onChange={(e) => setEditSizingMode(e.target.value)}
                      className="w-full bg-[#080d16] border border-[#1e2a42] rounded-lg px-3 py-2 text-white"
                    >
                      <option value="AUTO">AUTO (Compounding)</option>
                      <option value="MANUAL">MANUAL (Fixed Lots)</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-slate-400 mb-1">Manual Lots (BTC)</label>
                    <input
                      type="number"
                      step="0.001"
                      min="0.001"
                      value={editManualLots}
                      onChange={(e) => setEditManualLots(e.target.value)}
                      className="w-full bg-[#080d16] border border-[#1e2a42] rounded-lg px-3 py-2 text-white"
                    />
                  </div>
                </div>

                <div className="flex justify-end space-x-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setConfigModalTenant(null)}
                    className="px-3 py-2 rounded-lg bg-[#151f33] text-slate-300 hover:text-white text-xs cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSavingConfig}
                    className="px-4 py-2 rounded-lg bg-[#00e5ff] hover:bg-[#33ebff] text-black font-bold text-xs transition cursor-pointer disabled:opacity-50"
                  >
                    {isSavingConfig ? 'Saving...' : 'Save Configuration'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
