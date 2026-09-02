import os

p = os.path.join('static', 'js', 'projects.js')
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

ICONS = {
  "overview": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><rect x=\"3\" y=\"4\" width=\"18\" height=\"18\" rx=\"2\" ry=\"2\"/><line x1=\"16\" y1=\"2\" x2=\"16\" y2=\"6\"/><line x1=\"8\" y1=\"2\" x2=\"8\" y2=\"6\"/><line x1=\"3\" y1=\"10\" x2=\"21\" y2=\"10\"/><path d=\"M8 14h8\"/><path d=\"M8 18h4\"/></svg>",
  "notes": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M12 20h9\"/><path d=\"M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z\"/></svg>",
  "docs": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z\"/><polyline points=\"14 2 14 8 20 8\"/><line x1=\"16\" y1=\"13\" x2=\"8\" y2=\"13\"/><line x1=\"16\" y1=\"17\" x2=\"8\" y2=\"17\"/><polyline points=\"10 9 9 9 8 9\"/></svg>",
  "links": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71\"/><path d=\"M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71\"/></svg>",
  "checklist": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><polyline points=\"9 11 12 14 22 4\"/><path d=\"M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11\"/></svg>",
  "attach": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48\"/></svg>",
  "pin": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><line x1=\"12\" y1=\"17\" x2=\"12\" y2=\"22\"/><path d=\"M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z\"/></svg>",
  "close": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><line x1=\"18\" y1=\"6\" x2=\"6\" y2=\"18\"/><line x1=\"6\" y1=\"6\" x2=\"18\" y2=\"18\"/></svg>",
  "agent": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><rect x=\"3\" y=\"11\" width=\"18\" height=\"10\" rx=\"2\"/><circle cx=\"12\" cy=\"5\" r=\"2\"/><path d=\"M12 7v4\"/><line x1=\"8\" y1=\"16\" x2=\"8\" y2=\"16\"/><line x1=\"16\" y1=\"16\" x2=\"16\" y2=\"16\"/></svg>",
  "trash": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><polyline points=\"3 6 5 6 21 6\"/><path d=\"M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2\"/></svg>",
  "edit": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M12 20h9\"/><path d=\"M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z\"/></svg>",
  "sync": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8\"/><path d=\"M3 3v5h5\"/><path d=\"M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16\"/><path d=\"M16 21v-5h5\"/></svg>",
  "download": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4\"/><polyline points=\"7 10 12 15 17 10\"/><line x1=\"12\" y1=\"15\" x2=\"12\" y2=\"3\"/></svg>",
  "search": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><circle cx=\"11\" cy=\"11\" r=\"8\"/><line x1=\"21\" y1=\"21\" x2=\"16.65\" y2=\"16.65\"/></svg>",
  "plus": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><line x1=\"12\" y1=\"5\" x2=\"12\" y2=\"19\"/><line x1=\"5\" y1=\"12\" x2=\"19\" y2=\"12\"/></svg>",
  "folder": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" style=\"opacity:0.7;\"><path d=\"M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z\"/></svg>",
  "filePdf": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z\"/><polyline points=\"14 2 14 8 20 8\"/><path d=\"M9 15h6\"/><path d=\"M9 11h6\"/></svg>",
  "fileImg": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><rect x=\"3\" y=\"3\" width=\"18\" height=\"18\" rx=\"2\" ry=\"2\"/><circle cx=\"8.5\" cy=\"8.5\" r=\"1.5\"/><polyline points=\"21 15 16 10 5 21\"/></svg>",
  "fileDoc": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" style=\"opacity:0.7;\"><path d=\"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z\"/><polyline points=\"14 2 14 8 20 8\"/><line x1=\"16\" y1=\"13\" x2=\"8\" y2=\"13\"/><line x1=\"16\" y1=\"17\" x2=\"8\" y2=\"17\"/><polyline points=\"10 9 9 9 8 9\"/></svg>",
  "checkCircle": "<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M22 11.08V12a10 10 0 1 1-5.93-9.14\"/><polyline points=\"22 4 12 14.01 9 11.01\"/></svg>",
  "largeAttach": "<svg width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" style=\"opacity:0.7;\"><path d=\"M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48\"/></svg>",
  "cross": "<svg width=\"11\" height=\"11\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2.5\" stroke-linecap=\"round\"><line x1=\"18\" y1=\"6\" x2=\"6\" y2=\"18\"/><line x1=\"6\" y1=\"6\" x2=\"18\" y2=\"18\"/></svg>"
}

code = code.replace("📋 Overview & Summary", ICONS["overview"] + " Overview & Summary")
code = code.replace("📝 Notes & To-Dos", ICONS["notes"] + " Notes & To-Dos")
code = code.replace("📁 Documents & Files", ICONS["docs"] + " Documents & Files")
code = code.replace("🔗 Linked Work", ICONS["links"] + " Linked Work")

code = code.replace("📝 Note", ICONS["notes"] + " Note")
code = code.replace("✓ Checklist", ICONS["checklist"] + " Checklist")
code = code.replace("📎 Attach File", ICONS["attach"] + " Attach File")
code = code.replace("✏️ Edit Manifest", ICONS["edit"] + " Edit Manifest")
code = code.replace("🔄 Sync Disk", ICONS["sync"] + " Sync Disk")
code = code.replace("🤖 Agent Session", ICONS["agent"] + " Agent Session")
code = code.replace(">✕ Close<", ">" + ICONS["close"] + " Close<")
code = code.replace(">✕<", ">" + ICONS["close"] + "<")
code = code.replace("⬇️ Download", ICONS["download"] + " Download")
code = code.replace("🔗 Copy Link", ICONS["links"] + " Copy Link")
code = code.replace("🔍 Search notes & tasks...", "Search notes & tasks...")

code = code.replace("title=\"Unpin\">📌</button>", "title=\"Unpin\">" + ICONS["pin"] + "</button>")
code = code.replace("title=\"Pin to top\">📌</button>", "title=\"Pin to top\">" + ICONS["pin"] + "</button>")
code = code.replace("style=\"cursor:pointer;\">\n            📎", "style=\"cursor:pointer;\">\n            " + ICONS["attach"])
code = code.replace("style=\"cursor:pointer;\">\r\n            📎", "style=\"cursor:pointer;\">\r\n            " + ICONS["attach"])
code = code.replace("title=\"Solve with Agent\">🤖</button>", "title=\"Solve with Agent\">" + ICONS["agent"] + "</button>")
code = code.replace("title=\"Delete Note\">🗑️</button>", "title=\"Delete Note\">" + ICONS["trash"] + "</button>")

code = code.replace("📌 Pinned", ICONS["pin"] + " Pinned")
code = code.replace("✓ Checklists", ICONS["checklist"] + " Checklists")
code = code.replace("📝 Notes", ICONS["notes"] + " Notes")
code = code.replace("📎 Files", ICONS["attach"] + " Files")

code = code.replace("<div style=\"font-size:24px; margin-bottom:6px;\">📄</div>", "<div style=\"margin-bottom:6px;\">" + ICONS["fileDoc"] + "</div>")
code = code.replace("<div style=\"font-size:24px; margin-bottom:6px;\">📁</div>", "<div style=\"margin-bottom:6px;\">" + ICONS["folder"] + "</div>")
code = code.replace("<div style=\"font-size:24px; margin-bottom:6px;\">📎</div>", "<div style=\"margin-bottom:6px;\">" + ICONS["largeAttach"] + "</div>")

code = code.replace("title=\"New checklist\">✓</button>", "title=\"New checklist\">" + ICONS["checklist"] + "</button>")
code = code.replace("title=\"New note\">📝</button>", "title=\"New note\">" + ICONS["notes"] + "</button>")
code = code.replace("title=\"Attach file\">📎</button>", "title=\"Attach file\">" + ICONS["attach"] + "</button>")

code = code.replace("<span>${isImg ? '🖼️' : '📄'}</span>", "<span>${isImg ? '" + ICONS['fileImg'] + "' : '" + ICONS['filePdf'] + "'}</span>")
code = code.replace("<span>${isPdf ? '📄' : '📝'}</span>", "<span>${isPdf ? '" + ICONS['filePdf'] + "' : '" + ICONS['notes'] + "'}</span>")

code = code.replace(">✕</span>", ">" + ICONS["cross"] + "</span>")
code = code.replace("✕ Close", ICONS["close"] + " Close")
code = code.replace("✕", ICONS["cross"])
code = code.replace("✓", ICONS["checklist"])

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)

print("Python replacements complete.")
