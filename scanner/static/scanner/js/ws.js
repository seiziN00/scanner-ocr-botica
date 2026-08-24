/* FarmaScan · WebSocket de sesión con reconexión automática.
 * Solo transporta eventos JSON livianos; el estado se pide por HTTP.
 */
(function () {
  "use strict";

  window.FarmaScan = window.FarmaScan || {};

  FarmaScan.connectSessionWS = function (sessionId, onEvent) {
    const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
    const url = proto + window.location.host + "/ws/sesion/" + sessionId + "/";
    let ws = null;
    let attempts = 0;
    let closedByServer = false;

    function connect() {
      ws = new WebSocket(url);

      ws.addEventListener("open", () => {
        const wasReconnect = attempts > 0;
        attempts = 0;
        if (wasReconnect) {
          /* se perdió la conexión: pedir el estado canónico al servidor */
          onEvent({ type: "_ws_reconnected", data: {} });
        } else {
          FarmaScan.toast("Sincronización activa", "ok");
        }
      });

      ws.addEventListener("message", (e) => {
        let msg;
        try {
          msg = JSON.parse(e.data);
        } catch (err) {
          return;
        }
        if (msg && msg.type && msg.type !== "pong") onEvent(msg);
      });

      ws.addEventListener("close", (e) => {
        if (e.code === 4429) {
          /* máximo de equipos: el aviso ya llegó como evento "error" */
          closedByServer = true;
          return;
        }
        if (e.code === 4404) {
          /* el aviso llegó como evento "error" (session_unavailable) */
          closedByServer = true;
          return;
        }
        if (closedByServer) return;
        attempts = Math.min(attempts + 1, 6);
        const delay = Math.min(1000 * attempts, 8000);
        setTimeout(connect, delay);
      });

      ws.addEventListener("error", () => ws.close());
    }

    connect();

    /* latido para detectar caídas silenciosas */
    setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, 25000);
  };
})();
