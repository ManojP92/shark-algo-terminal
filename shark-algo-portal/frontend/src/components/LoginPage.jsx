import React, { useState, useEffect, useRef } from 'react';
import { Shield, Lock, KeyRound, Send, ArrowRight, RefreshCw, CheckCircle2, AlertTriangle, Eye, EyeOff, Bot, Sparkles } from 'lucide-react';

export default function LoginPage({ onLoginSuccess }) {
  // Step 1: 'PASSWORD', Step 2: 'OTP'
  const [step, setStep] = useState('PASSWORD');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [otp, setOtp] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [chatHint, setChatHint] = useState('...6221');
  const [countdown, setCountdown] = useState(300); // 5 min
  const [resendCooldown, setResendCooldown] = useState(0);

  const otpInputRef = useRef(null);

  // Countdown timer for OTP expiry
  useEffect(() => {
    let timer = null;
    if (step === 'OTP' && countdown > 0) {
      timer = setInterval(() => {
        setCountdown((prev) => (prev > 0 ? prev - 1 : 0));
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [step, countdown]);

  // Resend cooldown timer
  useEffect(() => {
    let timer = null;
    if (resendCooldown > 0) {
      timer = setInterval(() => {
        setResendCooldown((prev) => (prev > 0 ? prev - 1 : 0));
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [resendCooldown]);

  // Auto-focus OTP input when entering OTP step
  useEffect(() => {
    if (step === 'OTP' && otpInputRef.current) {
      otpInputRef.current.focus();
    }
  }, [step]);

  // Format seconds to MM:SS
  const formatTime = (secs) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  // Step 1: Request 2FA OTP via Telegram
  const handleRequestOtp = async (e) => {
    if (e) e.preventDefault();
    if (!password.trim()) {
      setError('Please enter your Master Password.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const res = await fetch('/api/auth/request-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: password.trim() }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Authentication failed');
      }

      setChatHint(data.chat_id_hint || '...6221');
      setStep('OTP');
      setCountdown(data.expires_in || 300);
      setResendCooldown(60); // 60s cooldown for resend
    } catch (err) {
      setError(err.message || 'Connection error. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  // Step 2: Verify Telegram OTP
  const handleVerifyOtp = async (e) => {
    if (e) e.preventDefault();
    const cleanOtp = otp.trim();
    if (cleanOtp.length < 6) {
      setError('Please enter the full 6-digit verification code.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const res = await fetch('/api/auth/verify-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ otp: cleanOtp }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Invalid verification code');
      }

      // Save token and trigger login
      localStorage.setItem('shark_auth_token', data.token);
      if (onLoginSuccess) {
        onLoginSuccess(data.token, data.user);
      }
    } catch (err) {
      setError(err.message || 'Verification failed. Please check the code.');
    } finally {
      setLoading(false);
    }
  };

  // Resend OTP
  const handleResend = async () => {
    if (resendCooldown > 0) return;
    setOtp('');
    await handleRequestOtp();
  };

  return (
    <div className="min-h-screen bg-[#080b11] text-slate-100 flex flex-col justify-center items-center px-4 py-12 relative overflow-hidden selection:bg-[#00e5ff]/30">
      {/* Background Ambient Glows */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[550px] h-[550px] bg-[#00e5ff]/5 rounded-full blur-[130px] pointer-events-none" />
      <div className="absolute bottom-10 right-1/4 w-[350px] h-[350px] bg-emerald-500/5 rounded-full blur-[110px] pointer-events-none" />

      {/* Main Glass Authentication Card */}
      <div className="w-full max-w-md bg-[#0e1424]/90 backdrop-blur-xl border border-[#1b263b] rounded-2xl shadow-2xl shadow-black/80 p-7 sm:p-8 relative z-10">
        
        {/* Header Branding */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-[#17223b] to-[#0c1324] border border-[#263757] shadow-inner mb-3.5 group">
            <span className="text-3xl group-hover:scale-110 transition-transform">🦈</span>
          </div>
          <div className="flex items-center justify-center space-x-2">
            <h1 className="text-2xl font-black tracking-wider text-white">
              SHARK<span className="text-[#00e5ff]">QUANT</span>
            </h1>
            <span className="text-[10px] px-2 py-0.5 rounded font-mono font-bold tracking-widest bg-[#172136] text-[#00e5ff] border border-[#233150]">
              TERMINAL
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1 font-mono">
            Shark Exchange Futures • Protected by 2FA
          </p>
        </div>

        {/* Telegram 2FA Status Pill */}
        <div className="flex items-center justify-between px-3.5 py-2 bg-[#090d18] border border-[#1b263d] rounded-xl text-xs font-mono mb-6">
          <div className="flex items-center space-x-2 text-slate-300">
            <Bot className="w-4 h-4 text-[#00e5ff]" />
            <span>Telegram Bot Auth:</span>
          </div>
          <div className="flex items-center space-x-1.5 text-emerald-400 font-semibold">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>@ManyaBTCUSD_bot</span>
          </div>
        </div>

        {/* Error Alert Banner */}
        {error && (
          <div className="mb-5 p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-start space-x-2.5 text-xs text-rose-300 animate-in fade-in duration-200">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <div className="flex-1 font-mono">{error}</div>
          </div>
        )}

        {/* ── STEP 1: MASTER PASSWORD ── */}
        {step === 'PASSWORD' && (
          <form onSubmit={handleRequestOtp} className="space-y-4">
            <div>
              <label className="block text-xs font-mono font-medium text-slate-300 mb-1.5 flex items-center justify-between">
                <span>MASTER PASSWORD</span>
                <span className="text-[10px] text-slate-500">Default: shark2026</span>
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter administrator password..."
                  required
                  autoFocus
                  className="w-full pl-10 pr-10 py-2.5 bg-[#080d19] border border-[#1e2a44] focus:border-[#00e5ff] rounded-xl text-sm font-mono text-white placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-[#00e5ff] transition"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 hover:text-slate-200 cursor-pointer"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 px-4 bg-gradient-to-r from-[#00b4d8] to-[#0077b6] hover:from-[#00c2e8] hover:to-[#0088cc] text-white font-bold text-xs uppercase tracking-wider font-mono rounded-xl shadow-lg shadow-[#00b4d8]/20 transition flex items-center justify-center space-x-2 cursor-pointer disabled:opacity-50"
            >
              {loading ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>DISPATCHING 2FA TO TELEGRAM...</span>
                </>
              ) : (
                <>
                  <span>REQUEST 2FA CODE VIA TELEGRAM</span>
                  <Send className="w-3.5 h-3.5" />
                </>
              )}
            </button>
          </form>
        )}

        {/* ── STEP 2: TELEGRAM 2FA OTP VERIFICATION ── */}
        {step === 'OTP' && (
          <form onSubmit={handleVerifyOtp} className="space-y-4 animate-in fade-in duration-300">
            {/* Instruction Banner */}
            <div className="p-3 bg-[#0a1224] border border-[#1b2b4d] rounded-xl text-xs space-y-1">
              <div className="flex items-center justify-between text-slate-300 font-mono">
                <span className="flex items-center space-x-1.5">
                  <KeyRound className="w-3.5 h-3.5 text-[#00e5ff]" />
                  <span>Code sent to Telegram</span>
                </span>
                <span className={`font-bold ${countdown < 60 ? 'text-rose-400' : 'text-[#00e5ff]'}`}>
                  ⏱️ {formatTime(countdown)}
                </span>
              </div>
              <p className="text-[11px] text-slate-400">
                Check Telegram chat (<span className="text-slate-200 font-mono">ID: {chatHint}</span>) for your 6-digit one-time code.
              </p>
            </div>

            {/* 6-Digit OTP Field */}
            <div>
              <label className="block text-xs font-mono font-medium text-slate-300 mb-1.5">
                ENTER 6-DIGIT VERIFICATION CODE
              </label>
              <input
                ref={otpInputRef}
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength="6"
                value={otp}
                onChange={(e) => {
                  const val = e.target.value.replace(/\D/g, '');
                  setOtp(val);
                  if (val.length === 6) {
                    // Trigger verify if 6 digits entered
                    setTimeout(() => {
                      document.getElementById('verify-otp-submit-btn')?.click();
                    }, 100);
                  }
                }}
                placeholder="• • • • • •"
                className="w-full py-3 bg-[#080d19] border border-[#1e2a44] focus:border-[#00e5ff] rounded-xl text-center text-2xl font-mono tracking-[0.5em] text-[#00e5ff] placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-[#00e5ff] transition"
              />
            </div>

            <button
              id="verify-otp-submit-btn"
              type="submit"
              disabled={loading || otp.length < 6 || countdown === 0}
              className="w-full py-3 px-4 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold text-xs uppercase tracking-wider font-mono rounded-xl shadow-lg shadow-emerald-950/40 transition flex items-center justify-center space-x-2 cursor-pointer disabled:opacity-50"
            >
              {loading ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>VERIFYING CODE...</span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4" />
                  <span>UNLOCK SHARK TERMINAL</span>
                </>
              )}
            </button>

            {/* Resend & Back actions */}
            <div className="flex items-center justify-between text-xs font-mono pt-2 border-t border-[#162136]">
              <button
                type="button"
                onClick={() => {
                  setStep('PASSWORD');
                  setOtp('');
                  setError('');
                }}
                className="text-slate-400 hover:text-slate-200 transition cursor-pointer"
              >
                ← Change Password
              </button>

              <button
                type="button"
                onClick={handleResend}
                disabled={resendCooldown > 0 || loading}
                className="text-[#00e5ff] hover:text-[#5ce1e6] transition disabled:opacity-40 disabled:hover:text-[#00e5ff] cursor-pointer"
              >
                {resendCooldown > 0 ? `Resend code in ${resendCooldown}s` : 'Resend code via Telegram'}
              </button>
            </div>
          </form>
        )}

        {/* Security Notice Footer */}
        <div className="mt-6 pt-4 border-t border-[#152033] text-center">
          <p className="text-[10px] text-slate-500 font-mono flex items-center justify-center space-x-1.5">
            <Shield className="w-3 h-3 text-slate-400" />
            <span>End-to-end HMAC SHA-256 authenticated session</span>
          </p>
        </div>
      </div>
    </div>
  );
}
