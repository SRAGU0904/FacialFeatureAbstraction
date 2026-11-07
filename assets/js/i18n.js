"use strict";
// Only interface strings are localized. Scene IDs and demographic codes stay stable.
(() => {
  const messages = {
    en: {
      title: "FoodFace — Portrait Collage Studio",
      task: "Your task",
      taskGoal:
        "Create a food-face collage through visual association. Use and combine the supplied foods freely to stand in for facial features and capture what is distinctive about the person.",
      taskRules:
        "Complete both portraits. There is no time limit or limit on how many food items you use; you may reuse any item. You can move, rotate, flip and resize foods proportionally.",
      taskSubmit:
        "Edit freely before submitting. Submitting generates your result in JSON format. Before leaving, copy and send each portrait's result to the developer. Refreshing starts a new session and clears the current content.",
      original: "Original",
      collage: "Collage",
      library: "Food library",
      clear: "Clear",
      submit: "Submit portrait",
      submitted: "Submitted",
      research: "Research participation",
      notice:
        "Your collage and the details below will be used only for academic research. By copying and sending your result JSON to the developer, you consent to this research use. Nothing is sent automatically.",
      participant: "Participant details",
      gender: "Gender",
      age: "Age",
      nationality: "Nationality",
      feedback: "Other suggestions or comments (optional)",
      select: "Select",
      female: "Female",
      male: "Male",
      nonBinary: "Non-binary",
      other: "Other",
      notSay: "Prefer not to say",
      participantHint:
        "Complete the required fields before submitting. The same details apply to both portraits and are fixed after the first submission.",
      result: "Result JSON",
      resultHelp:
        "Copy this JSON and send it to the website developer. Copy each portrait's result before leaving this page.",
      copy: "Copy JSON",
      noSelection: "No selection",
      size: "Size",
      rotation: "Rotation",
      flipH: "Flip horizontal",
      flipV: "Flip vertical",
      backward: "Backward",
      forward: "Forward",
      duplicate: "Duplicate",
      delete: "Delete",
      layers: "Layers",
      confirmTitle: "Submit this portrait?",
      confirmDescription:
        "This will finalize the portrait and generate its result JSON. You cannot edit it afterward. Copy and send the JSON yourself; nothing is sent automatically.",
      keepEditing: "Keep editing",
      confirm: "Submit final portrait",
      loading: "Loading…",
      progress:
        "{count}/2 portraits submitted. Complete both portraits in any order and submit each separately.",
      completed:
        "Both portraits submitted. Copy and send both result JSONs to the website developer. Thank you.",
      submittedStatus: "Submitted — copy and send the result JSON.",
      draftStatus: "Not submitted. Refreshing starts a new session.",
      itemOne: "{count} item",
      itemMany: "{count} items",
      addFood: "Add {name}",
      originalAlt: "{name} — original",
      jsonReady:
        "Result JSON ready. Copy and send it to the website developer.",
      copied: "Copied. Send it to the website developer.",
      manualCopy:
        "Copy is unavailable. The JSON is selected; press Cmd/Ctrl+C to copy it.",
      loadError:
        "Could not load assets. Please reload the page or open Start FoodFace.command.",
      choosePortrait: "Choose a portrait",
      studio: "Portrait collage studio",
      canvas:
        "Collage canvas. Drag to move, use the lower-right handle to resize, and the top handle to rotate.",
      deleteSelected: "Delete selected food",
      flipHSelected: "Flip selected food horizontally",
      flipVSelected: "Flip selected food vertically",
      undo: "Undo",
      redo: "Redo",
      undoTitle: "Undo (Cmd/Ctrl+Z)",
      redoTitle: "Redo (Cmd/Ctrl+Shift+Z)",
      editSelected: "Edit selected food",
      transformSelected: "Transform selected food",
      mirrorH: "Mirror left to right",
      mirrorV: "Mirror top to bottom",
      backwardTitle: "Move back one layer",
      forwardTitle: "Move forward one layer",
      duplicateTitle: "Duplicate (Cmd/Ctrl+D)",
      deleteTitle: "Delete (Delete/Backspace)",
      selectFood: "Select food on the canvas",
      genderRequired: "Select a gender option.",
      ageRequired: "Enter a whole-number age from 1 to 120.",
      nationalityRequired: "Enter your nationality (up to 80 characters).",
      "portrait.zhu": "Zhu Yuanzhang",
      "portrait.euro": "Rudolf II",
      "artist.euro": "Hans von Aachen",
      "food.pumpkin": "Pumpkin",
      "food.mango": "Mango",
      "food.potato": "Potato",
      "food.pear": "Pear",
      "food.chili": "Chili",
      "food.lettuce": "Lettuce",
      "food.shiitake": "Shiitake",
      "food.eggplant": "Eggplant",
      "food.blueberry": "Blueberry",
      "food.banana": "Banana",
      "food.bean": "Green bean",
      "food.cucumber": "Cucumber",
      "food.carrot": "Carrot",
      "food.walnut": "Walnut",
      "food.ginger": "Ginger",
      "food.strawberry": "Strawberry",
    },
    zh: {
      title: "FoodFace — 食物肖像拼贴工作台",
      task: "任务说明",
      taskGoal: "通过视觉联想完成食物人脸拼贴。自由使用和组合提供的食物来替代面部特征，并表现人物的独特之处。",
      taskRules:
        "请完成两幅肖像。不限时间和食物数量，同一种食物可重复使用。你可以移动、旋转、翻转和等比例缩放食物。",
      taskSubmit:
        "提交前可自由修改，提交后将生成一段JSON格式的结果。离开前请复制并把每幅肖像的结果发送给开发者。刷新页面会开始新会话，并清空当前内容。",
      original: "原图",
      collage: "拼贴",
      library: "食物素材",
      clear: "清空",
      submit: "提交肖像",
      submitted: "已提交",
      research: "研究参与说明",
      notice:
        "你的拼贴作品及以下信息将仅用于学术研究。复制结果 JSON 并发送给开发者，即表示你同意将这些内容用于学术研究。网页不会自动发送任何数据。",
      participant: "参与者信息",
      gender: "性别",
      age: "年龄",
      nationality: "国籍",
      feedback: "其他建议或留言（可选）",
      select: "请选择",
      female: "女",
      male: "男",
      nonBinary: "非二元性别",
      other: "其他",
      notSay: "不愿透露",
      participantHint:
        "请在提交前填写必填信息。两幅肖像使用同一份信息，首次提交后不可更改。",
      result: "结果 JSON",
      resultHelp:
        "请复制这段 JSON 并发送给网站开发者。离开页面前，请分别复制两幅肖像的结果。",
      copy: "复制 JSON",
      noSelection: "未选择",
      size: "大小",
      rotation: "旋转",
      flipH: "左右翻转",
      flipV: "上下翻转",
      backward: "下移一层",
      forward: "上移一层",
      duplicate: "复制食物",
      delete: "删除",
      layers: "图层",
      confirmTitle: "确定提交这幅肖像？",
      confirmDescription:
        "提交后将锁定这幅肖像并生成结果 JSON，之后不可修改。请自行复制并发送 JSON；网页不会自动发送任何数据。",
      keepEditing: "继续编辑",
      confirm: "确认提交",
      loading: "加载中…",
      progress: "已提交 {count}/2 幅肖像。请按任意顺序完成并分别提交两幅肖像。",
      completed:
        "两幅肖像均已提交。请将两份结果 JSON 复制并发送给网站开发者，谢谢！",
      submittedStatus: "已提交，请复制并发送结果 JSON。",
      draftStatus: "尚未提交。刷新页面会开始新会话。",
      itemOne: "{count} 个食物",
      itemMany: "{count} 个食物",
      addFood: "添加{name}",
      originalAlt: "{name}原图",
      jsonReady: "结果 JSON 已生成，请复制并发送给网站开发者。",
      copied: "已复制，请发送给网站开发者。",
      manualCopy: "无法自动复制。已选中 JSON，请按 Cmd/Ctrl+C 复制。",
      loadError: "素材加载失败，请刷新页面或运行 Start FoodFace.command。",
      choosePortrait: "选择肖像",
      studio: "肖像拼贴工作区",
      canvas: "拼贴画布：拖动可移动食物，右下角手柄可缩放，顶部手柄可旋转。",
      deleteSelected: "删除选中食物",
      flipHSelected: "左右翻转选中食物",
      flipVSelected: "上下翻转选中食物",
      undo: "撤销",
      redo: "重做",
      undoTitle: "撤销（Cmd/Ctrl+Z）",
      redoTitle: "重做（Cmd/Ctrl+Shift+Z）",
      editSelected: "编辑选中食物",
      transformSelected: "调整选中食物",
      mirrorH: "左右镜像翻转",
      mirrorV: "上下镜像翻转",
      backwardTitle: "下移一层",
      forwardTitle: "上移一层",
      duplicateTitle: "复制食物（Cmd/Ctrl+D）",
      deleteTitle: "删除（Delete/Backspace）",
      selectFood: "选择画布中的食物",
      genderRequired: "请选择性别选项。",
      ageRequired: "请输入 1 至 120 之间的整数年龄。",
      nationalityRequired: "请填写国籍（不超过 80 个字符）。",
      "portrait.zhu": "朱元璋",
      "portrait.euro": "鲁道夫二世",
      "artist.euro": "汉斯·冯·亚琛",
      "food.pumpkin": "南瓜",
      "food.mango": "芒果",
      "food.potato": "土豆",
      "food.pear": "梨",
      "food.chili": "辣椒",
      "food.lettuce": "生菜",
      "food.shiitake": "香菇",
      "food.eggplant": "茄子",
      "food.blueberry": "蓝莓",
      "food.banana": "香蕉",
      "food.bean": "豆角",
      "food.cucumber": "黄瓜",
      "food.carrot": "胡萝卜",
      "food.walnut": "核桃",
      "food.ginger": "生姜",
      "food.strawberry": "草莓",
    },
  };
  const i18n = {
    language: "en",
    t(key, values = {}, language = this.language) {
      return (messages[language][key] ?? messages.en[key] ?? key).replace(
        /\{(\w+)\}/g,
        (_, name) => String(values[name] ?? `{${name}}`),
      );
    },
    apply(language) {
      if (!messages[language]) return;
      this.language = language;
      document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
      document.querySelectorAll("[data-i18n]").forEach((el) => {
        el.textContent = this.t(el.dataset.i18n);
      });
      for (const attribute of ["title", "aria-label"]) {
        document.querySelectorAll(`[data-i18n-${attribute}]`).forEach((el) => {
          el.setAttribute(
            attribute,
            this.t(el.getAttribute(`data-i18n-${attribute}`)),
          );
        });
      }
      document.querySelectorAll("[data-language]").forEach((button) => {
        button.setAttribute(
          "aria-pressed",
          String(button.dataset.language === language),
        );
      });
    },
  };
  window.FOODFACE_I18N = i18n;
})();
