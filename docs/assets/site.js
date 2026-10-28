// The hero demo: bullets from examples/data/master.yaml, three listings, and the page each
// one would get. Selections are illustrative; the real app has Claude draft them and Typst
// measure the page.
(() => {
  const POSITIONS = [
    {
      id: "pixel-forge-sr", company: "Pixel Forge Studios", title: "Senior Gameplay Designer",
      game: "Robo Racers (Unity)", where: "Springfield, USA", dates: "Jan 2022 – Present",
      bullets: {
        "rr-boosts": ["Designed the boost and drafting system, balancing catch-up help for trailing racers against rewards for skilled racing lines, and tuned it across all 30 tracks", "gameplay, systems, balancing", 1],
        "rr-live": ["Ran weekly live events with rotating track modifiers, and used retention and completion data to decide which modifiers and rewards came back", "live-service, analytics", 1],
        "rr-lead": ["Led design for the ranked multiplayer mode from prototype through launch, including matchmaking and seasons", "leadership, multiplayer", 1],
        "rr-tools": ["Built an in-editor track tuning tool in C# used by the whole design team", "tools, unity", 1],
        "rr-bots": ["Designed the opponent AI difficulty tiers and tuned them from playtest data", "game-ai, unity", 2],
        "rr-playtests": ["Set up a weekly playtest loop with QA and turned each round of findings into a tuning pass", "playtesting, process", 2],
        "rr-mentor": ["Mentored two junior designers through their first shipped features", "mentorship", 3],
      },
    },
    {
      id: "dd-designer", company: "Lantern Games", title: "Gameplay Designer", team: "Combat Team",
      game: "Dungeon Delvers (Unreal Engine 4)", where: "Shelbyville, USA", dates: "Jun 2019 – Dec 2021",
      bullets: {
        "dd-bosses": ["Designed and scripted two boss encounters whose phases change with how well the party is doing, so a struggling group gets breathing room and a strong one gets pushed", "game-ai, gameplay", 1],
        "dd-enemies": ["Owned the design and scripting of six enemy types in Blueprints", "game-ai, unreal", 1],
        "dd-abilities": ["Built and balanced twelve player abilities in data tables with the systems designer, tuning cooldowns and damage so each class had a clear role in a party", "gameplay, balancing", 1],
        "dd-coop": ["Scaled enemy health, damage, and spawn counts for one to four players, and tested every party size at each milestone so solo play never felt like an afterthought", "multiplayer, balancing", 2],
        "dd-console": ["Tuned controller feel and performance on console development kits", "consoles, unreal", 2],
        "dd-ui": ["Prototyped the inventory screen and handed it to the UI team", "ui, unreal", 3],
      },
    },
    {
      id: "fd-associate", company: "Fox Den Interactive", title: "Associate Designer",
      game: "Pocket Golf (Unity)", where: "Springfield, USA", dates: "Jun 2017 – May 2019",
      bullets: {
        "pg-courses": ["Designed and scripted 40 courses across four seasonal updates", "live-service, gameplay", 1],
        "pg-physics": ["Tuned ball physics and wind so shots read clearly on a small screen", "gameplay, mobile", 2],
        "pg-funnel": ["Reworked the tutorial after funnel data showed a drop at the third hole, raising day-one retention", "analytics, ui", 2],
      },
    },
  ];

  const LISTINGS = {
    combat: {
      headline: "Senior Gameplay Designer | Combat, Enemies and Encounters, Balancing",
      reqs: ["Enemy and boss encounters", "Ability tuning and balance", "Co-op scaling, 1 to 4 players", "Iterate from playtests", "Console experience (nice)"],
      gaps: [],
      pick: { "pixel-forge-sr": ["rr-bots", "rr-boosts", "rr-playtests", "rr-lead"], "dd-designer": ["dd-bosses", "dd-enemies", "dd-abilities", "dd-coop", "dd-console"], "fd-associate": ["pg-physics", "pg-courses"] },
      skills: ["Unreal Engine 4/5, Unity, C#, C++, Perforce", "Combat Design, Enemy Design, Balancing, Prototyping, Playtesting"],
    },
    systems: {
      headline: "Senior Gameplay Designer | Systems, Balancing, Live Events",
      reqs: ["Design and tune core systems", "Balance from player data", "Live events and seasons", "Work with analytics (nice)"],
      gaps: ["Economy and progression"],
      pick: { "pixel-forge-sr": ["rr-boosts", "rr-live", "rr-lead", "rr-playtests", "rr-tools"], "dd-designer": ["dd-abilities", "dd-coop", "dd-bosses"], "fd-associate": ["pg-funnel", "pg-courses"] },
      skills: ["Unity, Unreal Engine 4/5, C#, C++, Perforce", "Systems Design, Balancing, Live Events, Playtesting, Prototyping"],
    },
    technical: {
      headline: "Senior Gameplay Designer | Technical Design, Tools, Prototyping",
      reqs: ["Build tools for designers", "Script in Blueprints", "C# or C++", "Prototype new features", "Console performance"],
      gaps: ["Python scripting (nice)"],
      pick: { "pixel-forge-sr": ["rr-tools", "rr-boosts", "rr-playtests", "rr-bots", "rr-mentor"], "dd-designer": ["dd-enemies", "dd-bosses", "dd-ui", "dd-console"], "fd-associate": ["pg-physics", "pg-courses"] },
      skills: ["C#, C++, Unreal Engine 4/5, Unity, Perforce", "Prototyping, Systems Design, Enemy Design, Balancing, Playtesting"],
    },
  };

  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const $ = (id) => document.getElementById(id);
  const list = $("m-list");
  if (!list) return;

  function renderMaster(order) {
    const total = POSITIONS.reduce((n, p) => n + Object.keys(p.bullets).length, 0);
    $("m-count").textContent = `${total} bullets`;
    list.innerHTML = POSITIONS.map((p) =>
      `<li class="m-pos">${esc(p.company)}</li>` +
      Object.entries(p.bullets).map(([id, [text, tags, pri]]) => {
        const n = order.indexOf(id) + 1;
        return `<li class="m-b${n ? " on" : ""}" data-id="${id}">
          <span class="n">${n || ""}</span>
          <span><span class="t">${esc(text)}</span>
          <span class="meta"><code>${id}</code> p${pri} ${esc(tags)}</span></span></li>`;
      }).join("")
    ).join("");
  }

  function updateMaster(order) {
    list.querySelectorAll(".m-b").forEach((li) => {
      const n = order.indexOf(li.dataset.id) + 1;
      li.classList.toggle("on", n > 0);
      li.querySelector(".n").textContent = n || "";
    });
  }

  function renderPage(l, animate) {
    let i = 0;
    const roles = POSITIONS.filter((p) => l.pick[p.id]?.length).map((p) => {
      const items = l.pick[p.id].map((id) => {
        const text = p.bullets[id][0];
        return `<li${animate ? ` class="in" style="--i:${i++}"` : ""}>${esc(text)}</li>`;
      }).join("");
      const team = p.team ? `<i>, ${esc(p.team)}</i>` : "";
      return `<div class="co">${esc(p.company)}<span>${esc(p.where)}</span></div>
        <div class="co"><span class="ro">${esc(p.title)}${team} <i>| ${esc(p.game)}</i></span><span>${esc(p.dates)}</span></div>
        <ul>${items}</ul>`;
    }).join("");
    $("paper").innerHTML = `<div class="pg">
      <div class="nm">Alex Example</div>
      <div class="hl">${esc(l.headline)}</div>
      <div class="ct">alex@example.com | (555) 010-0199 | Springfield, USA</div>
      <div class="sh">Experience</div>${roles}
      <div class="sh">Skills</div>
      <div class="sk"><b>Software:</b> ${esc(l.skills[0])}</div>
      <div class="sk"><b>Design:</b> ${esc(l.skills[1])}</div>
      <div class="sh">Education</div>
      <div class="co">Example State University<span>2013 – 2017</span></div></div>`;
    measure();
  }

  // Like the real build, but measured by the browser instead of Typst: how much of the
  // page's usable height the content takes, and how many lines are left.
  function measure() {
    const paper = $("paper"), cs = getComputedStyle(paper);
    const room = paper.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    const used = paper.querySelector(".pg").offsetHeight;
    const pct = Math.round((used / room) * 100);
    const free = Math.floor((room - used) / parseFloat(cs.lineHeight));
    $("fill-pct").textContent = pct > 100 ? "Over one page" : `1 page, ${pct}% full`;
    $("fill-note").textContent = pct > 100 ? "cut a bullet" : `about ${free} lines free`;
    $("fill-bar").style.width = `${Math.min(pct, 100)}%`;
  }

  function renderReqs(l) {
    $("reqs").innerHTML = l.reqs.map((r) => `<li>✓ ${esc(r)}</li>`).join("") +
      l.gaps.map((g) => `<li class="gap" title="The master has no bullet for this">${esc(g)}</li>`).join("");
  }

  const tabs = [...document.querySelectorAll(".listings [role=tab]")];
  function select(key, animate) {
    const l = LISTINGS[key];
    const order = POSITIONS.flatMap((p) => l.pick[p.id] || []);
    tabs.forEach((t) => {
      const on = t.dataset.l === key;
      t.setAttribute("aria-selected", on);
      t.tabIndex = on ? 0 : -1;
    });
    if (animate) updateMaster(order); else renderMaster(order);
    renderReqs(l);
    renderPage(l, animate);
  }

  tabs.forEach((t, i) => {
    t.addEventListener("click", () => select(t.dataset.l, true));
    t.addEventListener("keydown", (e) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (!step) return;
      const next = tabs[(i + step + tabs.length) % tabs.length];
      next.focus();
      select(next.dataset.l, true);
    });
  });
  select("combat", false);
  window.addEventListener("resize", measure);

  document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(b.dataset.copy);
      b.textContent = "Copied";
    } catch {
      b.textContent = "Select and copy";
    }
    setTimeout(() => { b.textContent = "Copy commands"; }, 1600);
  }));
})();
