// orgh 仕様理解度クイズ。questions.js の window.ORGH_QUIZ を読み、
// file:// で直接開いても動くよう fetch を使わない構成にしている。
(function () {
  "use strict";

  var BANK = window.ORGH_QUIZ;
  var STORE_KEY = "orgh-quiz-v1";
  var DIFFICULTIES = [
    { id: "basic", label: "基礎" },
    { id: "applied", label: "応用" },
    { id: "internals", label: "実装詳細" }
  ];

  var el = function (id) { return document.getElementById(id); };
  var catLabel = {};
  var catReading = {};
  BANK.categories.forEach(function (c) { catLabel[c.id] = c.label; catReading[c.id] = c.reading; });
  var diffLabel = {};
  DIFFICULTIES.forEach(function (d) { diffLabel[d.id] = d.label; });

  // ---- 学習履歴(localStorage。使えない環境ではメモリ上のみ) ----
  var memory = { runs: [], wrong: {} };

  function loadStore() {
    try {
      var raw = window.localStorage.getItem(STORE_KEY);
      if (raw) { memory = JSON.parse(raw); }
    } catch (e) { /* localStorage不可: メモリ上のみで動かす */ }
    if (!memory.runs) { memory.runs = []; }
    if (!memory.wrong) { memory.wrong = {}; }
    return memory;
  }

  function saveStore() {
    try {
      window.localStorage.setItem(STORE_KEY, JSON.stringify(memory));
    } catch (e) { /* 保存できなくても出題は継続する */ }
  }

  // ---- 出題設定 ----
  function chip(container, id, label, checked) {
    var wrap = document.createElement("label");
    wrap.className = "chip" + (checked ? " on" : "");
    var box = document.createElement("input");
    box.type = "checkbox";
    box.value = id;
    box.checked = checked;
    box.addEventListener("change", function () {
      wrap.classList.toggle("on", box.checked);
      updatePoolSize();
    });
    wrap.appendChild(box);
    wrap.appendChild(document.createTextNode(label));
    container.appendChild(wrap);
  }

  function selected(containerId) {
    var out = [];
    Array.prototype.forEach.call(el(containerId).querySelectorAll("input"), function (i) {
      if (i.checked) { out.push(i.value); }
    });
    return out;
  }

  function pool() {
    var cats = selected("categories");
    var diffs = selected("difficulties");
    return BANK.questions.filter(function (q) {
      return cats.indexOf(q.category) >= 0 && diffs.indexOf(q.difficulty) >= 0;
    });
  }

  function updatePoolSize() {
    var n = pool().length;
    el("pool-size").textContent = "該当 " + n + " 問";
    var count = el("count");
    if (parseInt(count.value, 10) > n) { count.value = String(Math.max(n, 1)); }
    count.max = String(Math.max(n, 1));
    el("start").disabled = n === 0;
  }

  function shuffle(arr) {
    var a = arr.slice();
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }

  function pick(list, n, weakFirst) {
    var shuffled = shuffle(list);
    if (weakFirst) {
      shuffled.sort(function (a, b) {
        return (memory.wrong[b.id] || 0) - (memory.wrong[a.id] || 0);
      });
    }
    return shuffled.slice(0, n);
  }

  // ---- 出題 ----
  var session = null;

  function startSession(questions, mode) {
    session = { questions: questions, mode: mode, index: 0, answers: [], picked: [], answered: false };
    el("setup").classList.add("hidden");
    el("result").classList.add("hidden");
    el("quiz").classList.remove("hidden");
    render();
  }

  function current() { return session.questions[session.index]; }

  function render() {
    var q = current();
    session.picked = [];
    session.answered = false;

    var total = session.questions.length;
    el("progress-fill").style.width = (session.index / total * 100) + "%";
    el("progress-text").textContent = (session.index + 1) + " / " + total;
    el("q-category").textContent = catLabel[q.category] || q.category;
    el("q-difficulty").textContent = diffLabel[q.difficulty] || q.difficulty;
    el("q-multi").classList.toggle("hidden", q.type !== "multi");
    el("q-text").textContent = q.question;

    var box = el("choices");
    box.innerHTML = "";
    q.choices.forEach(function (text, i) {
      var row = document.createElement("div");
      row.className = "choice";
      row.dataset.index = String(i);
      var key = document.createElement("span");
      key.className = "key";
      key.textContent = String(i + 1);
      var body = document.createElement("span");
      body.textContent = text;
      row.appendChild(key);
      row.appendChild(body);
      row.addEventListener("click", function () { toggle(i); });
      box.appendChild(row);
    });

    el("feedback").classList.add("hidden");
    el("feedback").className = "feedback hidden";
    el("submit").classList.remove("hidden");
    el("submit").disabled = true;
    el("next").classList.add("hidden");
  }

  function toggle(i) {
    if (session.answered) { return; }
    var q = current();
    var at = session.picked.indexOf(i);
    if (q.type === "single") {
      session.picked = at >= 0 ? [] : [i];
    } else if (at >= 0) {
      session.picked.splice(at, 1);
    } else {
      session.picked.push(i);
    }
    Array.prototype.forEach.call(el("choices").children, function (row, idx) {
      row.classList.toggle("on", session.picked.indexOf(idx) >= 0);
    });
    el("submit").disabled = session.picked.length === 0;
  }

  function same(a, b) {
    if (a.length !== b.length) { return false; }
    var x = a.slice().sort(), y = b.slice().sort();
    return x.every(function (v, i) { return v === y[i]; });
  }

  function submit() {
    if (session.answered || session.picked.length === 0) { return; }
    var q = current();
    var correct = same(session.picked, q.answer);
    session.answered = true;
    session.answers.push({ id: q.id, picked: session.picked.slice(), correct: correct });

    memory.wrong[q.id] = Math.max(0, (memory.wrong[q.id] || 0) + (correct ? -1 : 1));
    saveStore();

    if (session.mode === "learn") {
      Array.prototype.forEach.call(el("choices").children, function (row, idx) {
        if (q.answer.indexOf(idx) >= 0) { row.classList.add("correct"); }
        else if (session.picked.indexOf(idx) >= 0) { row.classList.add("wrong"); }
      });
      showFeedback(q, correct);
    }

    el("submit").classList.add("hidden");
    el("next").classList.remove("hidden");
    el("next").textContent = session.index + 1 < session.questions.length ? "次へ" : "結果を見る";
    el("next").focus();
  }

  function showFeedback(q, correct) {
    var box = el("feedback");
    box.className = "feedback " + (correct ? "ok" : "ng");
    box.innerHTML = "";
    var verdict = document.createElement("p");
    verdict.className = "verdict " + (correct ? "ok" : "ng");
    verdict.textContent = correct ? "正解" : "不正解";
    var exp = document.createElement("p");
    exp.textContent = q.explanation;
    var src = document.createElement("p");
    src.className = "muted";
    src.textContent = "出典: " + q.sources.join(" / ");
    box.appendChild(verdict);
    box.appendChild(exp);
    box.appendChild(src);
  }

  function next() {
    if (session.index + 1 < session.questions.length) {
      session.index += 1;
      render();
    } else {
      finish();
    }
  }

  // ---- 結果 ----
  function finish() {
    var byId = {};
    BANK.questions.forEach(function (q) { byId[q.id] = q; });

    var total = session.answers.length;
    var hit = session.answers.filter(function (a) { return a.correct; }).length;

    el("quiz").classList.add("hidden");
    el("result").classList.remove("hidden");
    el("score").innerHTML = Math.round(hit / total * 100) + "点 <small>(" + hit + " / " + total + " 問正解)</small>";

    var stats = {};
    session.answers.forEach(function (a) {
      var c = byId[a.id].category;
      if (!stats[c]) { stats[c] = { hit: 0, total: 0 }; }
      stats[c].total += 1;
      if (a.correct) { stats[c].hit += 1; }
    });

    var bars = el("by-category");
    bars.innerHTML = "";
    var weak = [];
    Object.keys(stats).forEach(function (c) {
      var s = stats[c];
      var rate = s.hit / s.total;
      if (rate < 0.7) { weak.push(c); }
      var row = document.createElement("div");
      row.className = "bar-row";
      row.innerHTML =
        '<span class="name"></span><span class="bar"><div></div></span><span class="num"></span>';
      row.querySelector(".name").textContent = catLabel[c] || c;
      var fill = row.querySelector(".bar > div");
      fill.style.width = (rate * 100) + "%";
      if (rate < 0.7) { fill.classList.add("low"); }
      row.querySelector(".num").textContent = s.hit + "/" + s.total;
      bars.appendChild(row);
    });

    var wa = el("weak-areas");
    wa.innerHTML = "";
    if (weak.length) {
      var h = document.createElement("h3");
      h.textContent = "重点復習(正答率70%未満)";
      wa.appendChild(h);
      var ul = document.createElement("ul");
      weak.forEach(function (c) {
        var li = document.createElement("li");
        li.textContent = (catLabel[c] || c) + " — " + (catReading[c] || "");
        ul.appendChild(li);
      });
      wa.appendChild(ul);
    }

    var review = el("review");
    review.innerHTML = "";
    session.answers.forEach(function (a) {
      var q = byId[a.id];
      var item = document.createElement("div");
      item.className = "review-item " + (a.correct ? "ok" : "ng");
      var qp = document.createElement("p");
      qp.className = "q";
      qp.textContent = q.question;
      item.appendChild(qp);
      if (!a.correct) {
        var yours = document.createElement("p");
        yours.className = "ans";
        yours.textContent = "あなたの回答: " + a.picked.map(function (i) { return q.choices[i]; }).join(" / ");
        item.appendChild(yours);
      }
      var right = document.createElement("p");
      right.className = "ans";
      right.textContent = "正解: " + q.answer.map(function (i) { return q.choices[i]; }).join(" / ");
      item.appendChild(right);
      var exp = document.createElement("p");
      exp.className = "ans";
      exp.textContent = q.explanation + "(出典: " + q.sources.join(" / ") + ")";
      item.appendChild(exp);
      review.appendChild(item);
    });

    memory.runs.unshift({
      at: new Date().toISOString().slice(0, 16).replace("T", " "),
      hit: hit, total: total
    });
    memory.runs = memory.runs.slice(0, 10);
    saveStore();
    renderHistory();

    var wrongIds = session.answers.filter(function (a) { return !a.correct; })
      .map(function (a) { return a.id; });
    el("retry-wrong").disabled = wrongIds.length === 0;
    el("retry-wrong").onclick = function () {
      startSession(shuffle(wrongIds.map(function (id) { return byId[id]; })), session.mode);
    };
  }

  function renderHistory() {
    var box = el("history");
    if (!memory.runs.length) { box.innerHTML = ""; return; }
    var html = "<strong>直近の記録</strong><ul>";
    memory.runs.forEach(function (r) {
      html += "<li>" + r.at + " — " + Math.round(r.hit / r.total * 100) + "点 (" + r.hit + "/" + r.total + ")</li>";
    });
    box.innerHTML = html + "</ul>";
  }

  // ---- 初期化 ----
  loadStore();
  BANK.categories.forEach(function (c) { chip(el("categories"), c.id, c.label, true); });
  DIFFICULTIES.forEach(function (d) { chip(el("difficulties"), d.id, d.label, true); });
  updatePoolSize();
  renderHistory();

  el("cat-all").addEventListener("click", function () {
    Array.prototype.forEach.call(el("categories").querySelectorAll("input"), function (i) {
      i.checked = true; i.parentNode.classList.add("on");
    });
    updatePoolSize();
  });
  el("cat-none").addEventListener("click", function () {
    Array.prototype.forEach.call(el("categories").querySelectorAll("input"), function (i) {
      i.checked = false; i.parentNode.classList.remove("on");
    });
    updatePoolSize();
  });

  el("start").addEventListener("click", function () {
    var list = pool();
    var n = Math.min(Math.max(parseInt(el("count").value, 10) || 1, 1), list.length);
    startSession(pick(list, n, el("weak-first").checked), el("mode").value);
  });

  el("submit").addEventListener("click", submit);
  el("next").addEventListener("click", next);
  el("abort").addEventListener("click", function () {
    el("quiz").classList.add("hidden");
    el("setup").classList.remove("hidden");
  });
  el("back").addEventListener("click", function () {
    el("result").classList.add("hidden");
    el("setup").classList.remove("hidden");
    updatePoolSize();
  });
  el("reset-history").addEventListener("click", function () {
    memory = { runs: [], wrong: {} };
    saveStore();
    renderHistory();
  });

  document.addEventListener("keydown", function (e) {
    if (el("quiz").classList.contains("hidden")) { return; }
    if (e.key >= "1" && e.key <= "9") {
      var i = parseInt(e.key, 10) - 1;
      if (i < current().choices.length) { toggle(i); }
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (session.answered) { next(); } else { submit(); }
    }
  });
})();
