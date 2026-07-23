/**
 * build-forms.gs — Google Apps Script: forms.spec.json -> Google Forms
 *
 * Consumes the spec from form_spec_generator.py and creates the pre / post /
 * follow-up Google Forms, each linked to its own response sheet. The re-contact
 * opt-in (type "recontact", internal_only) is built as a SEPARATE form so its
 * responses land in a DIFFERENT sheet — feedback stays anonymous/publishable,
 * contact stays internal-only.
 *
 * ⚠️ NOT executed in the repo/CI — Apps Script runs only inside Google. Validate:
 *   1) script.google.com -> new project -> paste this file
 *   2) paste forms.spec.json into SPEC below
 *   3) run buildAll(), authorize, check the created forms + linked sheets.
 *
 * Scope owned here = rendering only. Schema is owned by form_spec_generator.py.
 */

var SPEC = {/* paste forms.spec.json here */};

function buildAll() {
  if (!SPEC.forms) throw new Error('SPEC empty — paste forms.spec.json into SPEC.');
  var made = [];
  SPEC.forms.forEach(function (f) {
    made.push(buildForm(f));
    var hasRecontact = f.sections.some(function (s) {
      return s.items.some(function (i) { return i.type === 'recontact'; });
    });
    if (hasRecontact) made.push(buildRecontactForm(f));
  });
  Logger.log('Created:\n' + made.join('\n'));
  return made;
}

function buildForm(f) {
  var form = FormApp.create(f.title);
  form.setDescription('[' + f.when + ' · ' + f.channel + '] ' + (SPEC.meta.engagement || ''));
  form.setCollectEmail(false); // anonymous feedback track
  f.sections.forEach(function (sec) {
    if (sec.items.every(function (i) { return i.type === 'recontact'; })) return;
    if (sec.name) form.addSectionHeaderItem().setTitle(sec.name);
    sec.items.forEach(function (it) { if (it.type !== 'recontact') addItem(form, it); });
  });
  var ss = SpreadsheetApp.create(f.title + ' — 응답');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());
  shareWithReader(ss); // auto-share so fetch_responses.py can read — no manual step
  return f.key + ' -> form:' + form.getEditUrl() + '  sheet:' + ss.getUrl();
}

// Grant the response sheet to the reader service account at creation time, so no
// one ever shares sheets by hand. Email comes from the spec meta (from config).
function shareWithReader(ss) {
  var email = SPEC.meta && SPEC.meta.service_account_email;
  if (!email) return; // no reader configured -> skip silently
  try { SpreadsheetApp.openById(ss.getId()).addViewer(email); }
  catch (e) { Logger.log('WARN addViewer 실패(' + email + '): ' + e); }
}

function buildRecontactForm(parent) {
  var form = FormApp.create(parent.title + ' — 후속 연락 (선택)');
  form.setDescription('INTERNAL ONLY — 후속 발송 목적. 피드백 응답과 분리 저장.');
  var block = null;
  parent.sections.forEach(function (s) {
    s.items.forEach(function (i) { if (i.type === 'recontact') block = i; });
  });
  form.addSectionHeaderItem().setTitle('재접촉 동의 (분리 저장)');
  form.addMultipleChoiceItem().setTitle(block.q).setChoiceValues(['예', '아니오']).setRequired(true);
  form.addTextItem().setTitle('참가자 코드 (피드백과 join용)');
  form.addTextItem().setTitle('이름/호칭');
  form.addTextItem().setTitle('연락처 (이메일 / 카톡ID / 휴대폰 중 1)');
  form.addCheckboxItem().setTitle('후속 발송 목적에 한해 보관, 언제든 철회 가능 — 동의')
      .setChoiceValues(['동의']).setRequired(true);
  var ss = SpreadsheetApp.create(parent.title + ' — 연락처(INTERNAL)');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());
  shareWithReader(ss);
  return 'recontact -> form:' + form.getEditUrl() + '  sheet(INTERNAL):' + ss.getUrl();
}

function addItem(form, it) {
  switch (it.type) {
    case 'consent':
      form.addMultipleChoiceItem().setTitle(it.q)
          .setChoiceValues(['동의합니다', '동의하지 않습니다']).setRequired(!!it.required);
      break;
    case 'text':
      form.addTextItem().setTitle(it.q).setRequired(!!it.required);
      break;
    case 'scale':
      form.addScaleItem().setTitle(it.q).setBounds(1, (it.scale ? it.scale.length : 5))
          .setLabels('전혀', '매우').setRequired(!!it.required);
      break;
    case 'choice':
      form.addMultipleChoiceItem().setTitle(it.q).setChoiceValues(it.options).setRequired(!!it.required);
      break;
    case 'choice_multi':
      form.addCheckboxItem().setTitle(it.q).setChoiceValues(it.options);
      break;
    default:
      form.addTextItem().setTitle(it.q);
  }
}
