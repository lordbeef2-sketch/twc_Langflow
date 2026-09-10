(function () {
  "use strict";

  function addStyles() {
    if (document.getElementById("twc-openid-ui-style")) return;
    var style = document.createElement("style");
    style.id = "twc-openid-ui-style";
    style.textContent =
      'a[href="/settings/saml-sso"]{display:none!important}' +
      '#twc-openid-login{width:100%;margin-top:12px;padding:10px 14px;border-radius:6px;border:1px solid #6b7280;background:#111827;color:#fff;font-weight:600;cursor:pointer}' +
      '#twc-openid-login:hover{background:#1f2937}' +
      '#twc-openid-settings{margin-top:20px;padding:20px;border:1px solid hsl(var(--border));border-radius:8px;background:hsl(var(--background))}' +
      '#twc-openid-settings h3{font-size:16px;font-weight:600;margin:0 0 4px}' +
      '#twc-openid-settings p{font-size:12px;color:hsl(var(--muted-foreground));margin:0 0 16px}' +
      '#twc-openid-settings .twc-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}' +
      '#twc-openid-settings label{display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:500}' +
      '#twc-openid-settings input[type=text],#twc-openid-settings input[type=password]{height:40px;border:1px solid hsl(var(--border));border-radius:6px;background:transparent;padding:0 10px;color:inherit}' +
      '#twc-openid-settings .twc-full{grid-column:1/-1}' +
      '#twc-openid-settings .twc-row{display:flex;align-items:center;justify-content:space-between;margin-top:18px}' +
      '#twc-openid-settings .twc-toggle{display:flex;flex-direction:row;align-items:center;gap:8px}' +
      '#twc-openid-settings button{border:0;border-radius:6px;background:#2563eb;color:#fff;padding:9px 14px;font-weight:600;cursor:pointer}' +
      '#twc-openid-settings button:disabled{opacity:.6;cursor:wait}' +
      '#twc-openid-settings .twc-status{font-size:12px;color:hsl(var(--muted-foreground));margin:12px 0 0}' +
      '@media(max-width:700px){#twc-openid-settings .twc-grid{grid-template-columns:1fr}#twc-openid-settings .twc-full{grid-column:auto}}';
    document.head.appendChild(style);
  }

  function textValue(element) {
    return (element && element.value ? element.value : "").trim();
  }

  function baseFromDiscovery(value) {
    try {
      var url = new URL(value);
      var marker = "/authentication/";
      var index = url.pathname.indexOf(marker);
      url.pathname = index >= 0 ? (url.pathname.slice(0, index) || "/") : "/";
      url.search = "";
      url.hash = "";
      return url.toString().replace(/\/$/, "");
    } catch (_) {
      return "";
    }
  }

  function publicFromRedirect(value) {
    try {
      var url = new URL(value);
      url.pathname = "/";
      url.search = "";
      url.hash = "";
      return url.toString().replace(/\/$/, "");
    } catch (_) {
      return window.location.origin;
    }
  }

  function getField(panel, name) {
    return panel.querySelector('[data-twc-field="' + name + '"]');
  }

  function renderSettingsPanel(page) {
    var nativeForm = page.querySelector("form");
    if (nativeForm) nativeForm.style.display = "none";
    // This build's stock SSO card controls the native OAuth/SAML lane.  The
    // Workbench integration owns the page instead, so leave one unambiguous
    // TWC OpenID control and avoid the unused native metadata request.
    var nativeCard = page.children && page.children[1];
    if (nativeCard) nativeCard.style.display = "none";
    var panel = page.querySelector("#twc-openid-settings");
    if (panel) return panel;
    panel = document.createElement("section");
    panel.id = "twc-openid-settings";
    panel.innerHTML =
      '<h3>TWC OpenID</h3>' +
      '<p>Use the same Workbench setup. Langflow derives the Refresh3 OIDC endpoints and uses the live TWC user for authorization.</p>' +
      '<div class="twc-grid">' +
      '<label class="twc-full">Teamwork Cloud base URL<input type="text" data-twc-field="base" placeholder="https://twc-host:8443"></label>' +
      '<label>OpenID application ID<input type="text" data-twc-field="client" placeholder="twcworkbench"></label>' +
      '<label>Client secret<input type="password" data-twc-field="secret" placeholder="Enter client secret"></label>' +
      '<label class="twc-full">Langflow public URL<input type="text" data-twc-field="public" placeholder="https://langflow.example.com"></label>' +
      '</div>' +
      '<div class="twc-row"><label class="twc-toggle"><input type="checkbox" data-twc-field="enabled"> Enable TWC OpenID sign-in</label><button type="button" data-twc-action="save">Save TWC OpenID</button></div>' +
      '<div class="twc-status" data-twc-status></div>';
    page.appendChild(panel);
    panel.querySelector('[data-twc-action="save"]').addEventListener("click", function () {
      saveSettings(panel);
    });
    loadSettings(panel);
    return panel;
  }

  async function loadSettings(panel) {
    var status = panel.querySelector("[data-twc-status]");
    try {
      var response = await fetch("/api/v1/sso/config", { credentials: "include", headers: {} });
      if (!response.ok) throw new Error("Unable to load the current TWC OpenID settings.");
      var rows = await response.json();
      var config = Array.isArray(rows) ? rows[0] : null;
      if (!config) return;
      getField(panel, "base").value = baseFromDiscovery(config.discovery_url || "");
      getField(panel, "client").value = config.client_id || "";
      getField(panel, "public").value = publicFromRedirect(config.redirect_uri || "");
      getField(panel, "enabled").checked = !!config.enabled;
      status.textContent = config.has_client_secret ? "Existing client secret is stored securely; leave it blank to keep it." : "";
    } catch (error) {
      status.textContent = error.message || String(error);
    }
  }

  async function saveSettings(panel) {
    var button = panel.querySelector('[data-twc-action="save"]');
    var status = panel.querySelector("[data-twc-status]");
    var base = textValue(getField(panel, "base")).replace(/\/$/, "");
    var client = textValue(getField(panel, "client"));
    var publicUrl = textValue(getField(panel, "public")).replace(/\/$/, "") || window.location.origin;
    var secret = textValue(getField(panel, "secret"));
    if (!base || !client) {
      status.textContent = "Teamwork Cloud base URL and application ID are required.";
      return;
    }
    var body = {
      provider: "oidc",
      provider_name: "twc-openid",
      enabled: !!getField(panel, "enabled").checked,
      client_id: client,
      discovery_url: base + "/authentication/.well-known/oidc-configuration",
      redirect_uri: publicUrl + "/api/v1/sso/callback",
      scopes: "openid",
      email_claim: "email",
      username_claim: "preferred_username",
      user_id_claim: "sub"
    };
    if (secret) body.client_secret = secret;
    button.disabled = true;
    status.textContent = "Saving TWC OpenID settings...";
    try {
      var response = await fetch("/api/v1/sso/config", {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      var result = await response.json().catch(function () { return {}; });
      if (!response.ok) throw new Error(result.detail || "Unable to save TWC OpenID settings.");
      getField(panel, "secret").value = "";
      status.textContent = "Saved. TWC OpenID uses the Workbench endpoint and live-user flow.";
    } catch (error) {
      status.textContent = error.message || String(error);
    } finally {
      button.disabled = false;
    }
  }

  function addSettingsPanel() {
    if (!/\/settings\/oauth-sso(?:\/|$)/.test(window.location.pathname)) return;
    var heading = document.querySelector('[data-testid="settings_oauth_sso_header"]');
    if (!heading) return;
    // Langflow 1.12 renders the native provider form only after SSO is enabled.
    // Anchor to the page section itself so the TWC form is available while the
    // native form is absent, instead of silently rendering nothing.
    var page = heading.parentElement && heading.parentElement.parentElement && heading.parentElement.parentElement.parentElement;
    if (page) renderSettingsPanel(page);
  }

  function addLoginButton() {
    if (!/\/login(?:\/|$)/.test(window.location.pathname)) return;
    if (document.getElementById("twc-openid-login")) return;
    var form = document.querySelector("form");
    if (!form) return;
    var button = document.createElement("button");
    button.id = "twc-openid-login";
    button.type = "button";
    button.textContent = "Sign in with TWC OpenID";
    button.addEventListener("click", function () {
      var next = window.location.pathname + window.location.search;
      window.location.assign("/api/v1/sso/start/twc-openid?next=" + encodeURIComponent(next));
    });
    form.appendChild(button);
  }

  function boot() {
    addStyles();
    addLoginButton();
    addSettingsPanel();
  }

  new MutationObserver(boot).observe(document.documentElement, { childList: true, subtree: true });
  boot();
})();
