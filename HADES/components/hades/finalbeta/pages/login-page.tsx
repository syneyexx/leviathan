"use client";

import { useEffect, useRef, useState, type FormEvent, type MouseEvent } from "react";
import { HadesBrandLogo } from "../brand-logo";
import { FbIcon } from "../icons";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

export function LoginPage({ onNavigate }: Props) {
  const [showPass, setShowPass] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    };
  }, []);

  const showToast = (message: string) => {
    setToast(message);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 1400);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    onNavigate("dashboard");
  };

  const onClick = (event: MouseEvent<HTMLDivElement>) => {
    const toastEl = (event.target as HTMLElement).closest<HTMLElement>("[data-toast]");
    if (toastEl?.dataset.toast) {
      event.preventDefault();
      showToast(toastEl.dataset.toast);
    }
  };

  return (
    <div className="login-shell" onClick={onClick}>
      <header className="login-topbar">
        <button type="button" aria-label="Thema" data-toast="Thema (demo)">
          <FbIcon name="bolt" size={15} />
        </button>
        <button type="button" data-toast="Taal (demo)">
          <FbIcon name="globe" size={15} />
          Nederlands
          <FbIcon name="chevron" size={12} />
        </button>
      </header>

      <div className="login-body">
        <aside className="login-hero">
          <div className="login-hero-bg" aria-hidden="true" />
          <div className="login-hero-inner">
            <div className="login-brand">
              <HadesBrandLogo className="login-brand-logo" />
            </div>
            <div className="login-hero-motto">
              Higher Intelligence
              <br />
              A Brighter Tomorrow
            </div>
            <div className="login-hero-card">
              <p className="login-hero-quote">“Sovereign AI. Local power. Infinite possibilities.”</p>
              <div className="login-hero-side">Discipline creates freedom.</div>
            </div>
          </div>
        </aside>

        <main className="login-center">
          <form className="login-card" onSubmit={onSubmit}>
            <div className="login-card-brand">
              <HadesBrandLogo className="login-brand-logo login-brand-logo--card" />
              <div className="login-card-eco">LOCAL AI ECOSYSTEM</div>
            </div>

            <h1 className="login-title">Welkom terug</h1>
            <p className="login-sub">Veilige toegang tot het HADES platform.</p>

            <div className="login-field">
              <label htmlFor="fb-user">E-mail of gebruikersnaam</label>
              <div className="login-input">
                <FbIcon name="user" size={16} />
                <input id="fb-user" name="user" type="text" placeholder="jouw@email.nl of gebruikersnaam" autoComplete="username" />
              </div>
            </div>

            <div className="login-field">
              <label htmlFor="fb-pass">Wachtwoord</label>
              <div className="login-input">
                <FbIcon name="shield" size={16} />
                <input
                  id="fb-pass"
                  name="pass"
                  type={showPass ? "text" : "password"}
                  placeholder="••••••••"
                  autoComplete="current-password"
                />
                <button className="eye" type="button" aria-label="Toon wachtwoord" onClick={() => setShowPass((v) => !v)}>
                  <FbIcon name="external" size={16} />
                </button>
              </div>
            </div>

            <div className="login-row">
              <label className="login-check">
                <input type="checkbox" name="remember" /> Onthoud dit apparaat
              </label>
              <button className="login-link" type="button" data-toast="Wachtwoord herstellen (demo)">
                Wachtwoord vergeten?
              </button>
            </div>

            <details className="login-2fa" open>
              <summary>
                <FbIcon name="shield" size={15} />
                2FA code (optioneel)
                <FbIcon name="chevron" size={14} className="chev" />
              </summary>
              <div className="login-2fa-body">
                <div className="login-input">
                  <input type="text" name="otp" inputMode="numeric" maxLength={6} placeholder="6-cijferige code" />
                </div>
                <div className="hint">Gebruik je authenticator app indien ingeschakeld.</div>
              </div>
            </details>

            <button className="login-submit" type="submit">
              Inloggen
              <FbIcon name="chevron" size={16} />
            </button>

            <div className="login-divider">Of log in met</div>

            <div className="login-alts">
              <button className="login-alt" type="button" data-toast="Lokale account" onClick={() => onNavigate("dashboard")}>
                <FbIcon name="grid" size={18} />
                Lokaal
              </button>
              <button className="login-alt" type="button" data-toast="MCP / Workspace">
                <FbIcon name="link" size={18} />
                MCP
              </button>
              <button className="login-alt" type="button" data-toast="Single Sign-On">
                <FbIcon name="users" size={18} />
                SSO
              </button>
            </div>

            <button className="login-request" type="button" data-toast="Account aanvragen (demo)">
              <FbIcon name="user" size={16} />
              Account aanvragen
              <FbIcon name="chevron" size={14} className="chev" />
            </button>
          </form>
        </main>

        <aside className="login-aside">
          <section className="login-widget">
            <div className="login-widget-head">
              <FbIcon name="shield" size={15} />
              <span className="login-widget-title">Beveiligingsstatus</span>
              <button className="login-widget-link" type="button" data-toast="Details">
                Details
              </button>
            </div>
            <div className="login-status-line">
              <span className="dot" /> Alle systemen beveiligd
            </div>
            <div className="login-kv">
              <span>Firewall</span>
              <span className="ok">Actief</span>
            </div>
            <div className="login-kv">
              <span>Encryptie</span>
              <span className="ok">AES-256</span>
            </div>
            <div className="login-kv">
              <span>2FA policy</span>
              <span>Optioneel</span>
            </div>
            <div className="login-kv">
              <span>Threat level</span>
              <span className="ok">Laag</span>
            </div>
          </section>

          <section className="login-widget">
            <div className="login-widget-head">
              <FbIcon name="database" size={15} />
              <span className="login-widget-title">Lokale backend</span>
            </div>
            <div className="login-kv">
              <span>API</span>
              <span className="ok">Online</span>
            </div>
            <div className="login-kv">
              <span>SQLite</span>
              <span className="ok">OK</span>
            </div>
            <div className="login-kv">
              <span>LM Studio</span>
              <span>Gereed</span>
            </div>
            <div className="login-kv">
              <span>Plugins</span>
              <span>12 actief</span>
            </div>
          </section>

          <section className="login-widget">
            <div className="login-widget-head">
              <FbIcon name="settings" size={15} />
              <span className="login-widget-title">Systeeminformatie</span>
            </div>
            <div className="login-kv">
              <span>Host</span>
              <span>DESKTOP-HADES</span>
            </div>
            <div className="login-kv">
              <span>OS</span>
              <span>Windows 11</span>
            </div>
            <div className="login-kv">
              <span>Versie</span>
              <span>FINALBETA 0.9.0</span>
            </div>
            <div className="login-kv">
              <span>Uptime</span>
              <span>14u 22m</span>
            </div>
          </section>

          <section className="login-widget">
            <div className="login-widget-head">
              <FbIcon name="clock" size={15} />
              <span className="login-widget-title">Laatste login</span>
            </div>
            <div className="login-kv">
              <span>Gebruiker</span>
              <span>strijder</span>
            </div>
            <div className="login-kv">
              <span>Tijd</span>
              <span>vandaag 09:14</span>
            </div>
            <div className="login-kv">
              <span>IP</span>
              <span>127.0.0.1</span>
            </div>
            <div className="login-kv">
              <span>Apparaat</span>
              <span>Deze PC</span>
            </div>
          </section>

          <blockquote className="login-aside-quote">Discipline creates freedom.</blockquote>
        </aside>
      </div>

      <footer className="login-footer">
        <span>HADES FINALBETA · Local AI Platform</span>
        <span>Offline-first · Geen cloud vereist</span>
      </footer>

      <div className="fb-toast" style={{ opacity: toast ? 1 : 0 }} aria-live="polite">
        {toast ?? "Demoactie"}
      </div>
    </div>
  );
}
