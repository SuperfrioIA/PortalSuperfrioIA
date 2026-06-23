/* Roda no <head>, antes do primeiro paint. Se já existe sessão salva, esconde
   a tela de login imediatamente — senão ela pisca no F5 até o app.js decidir o
   estado (loadPortal é assíncrono). app.js remove esse style ao mostrar o login.
   A chave precisa bater com TOKEN_KEY do app.js ("sf_portal_token"). */
(function () {
  try {
    if (localStorage.getItem("sf_portal_token")) {
      var s = document.createElement("style");
      s.id = "boot-hide-login";
      s.textContent = "#screen-login{display:none!important}";
      document.head.appendChild(s);
    }
  } catch (e) {}
})();
