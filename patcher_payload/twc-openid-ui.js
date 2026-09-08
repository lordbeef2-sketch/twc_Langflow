(function () {
  "use strict";

  function addStyles() {
    if (document.getElementById("twc-openid-ui-style")) return;
    var style = document.createElement("style");
    style.id = "twc-openid-ui-style";
    style.textContent =
      'a[href="/settings/saml-sso"]{display:none!important}' +
      '#twc-openid-login{width:100%;margin-top:12px;padding:10px 14px;border-radius:6px;border:1px solid #6b7280;background:#111827;color:#fff;font-weight:600;cursor:pointer}' +
      '#twc-openid-login:hover{background:#1f2937}';
    document.head.appendChild(style);
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
  }

  new MutationObserver(boot).observe(document.documentElement, { childList: true, subtree: true });
  boot();
})();
