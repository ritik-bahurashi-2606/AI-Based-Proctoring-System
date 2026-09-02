var nos = [];
var curr = 0;
var data = {};
var examUrl = window.location.pathname;
var timerInterval = null;
var timeSyncInterval = null;
const NOT_MARKED=0;
const MARKED=1;
const BOOKMARKED=2;
const MARKED_BOOKMARKED=3;
const SUBMITTED = 4;
const SUBMITTED_BOOKMARKED = 5;

function mySnackBar() {
    var x = document.getElementById("snackbar");
    x.className = "show";
    setTimeout(function(){ x.className = x.className.replace("show", ""); }, 10000);
  }

// NOTE: Tab-switch and blur events are handled by proctoring_common.js
// The onfocus handler was incorrectly logging window events — removed.

function startExamProctoring() {
    if (typeof window.startStreaming === 'function') {
        window.startStreaming();
    }
    if (typeof window.captureSnapshot === 'function') {
        window.captureSnapshot();
    }
}

$(document).ready( function() {
    var url = window.location.href;
    var list = url.split('/');
    $('.question').remove();
    if (url.includes('/give-test/')) {
        $.ajax({
            type:"POST",
            url:"/randomize",
            dataType:"json",
            data : {id: list[list.length-1]},
            success: function(temp) {
                nos = temp || [];
                make_array();
                display_ques(1);
                ques_grid();
            }
        });
    }
    var time = parseInt($('#time').text()), display = $('#time');
    startTimer(time, display);
    sendTime();
    flag_time = true;

})

var unmark_all = function() {
    $('#options td').each(function(i) 
    {
        $(this).css("background-color",'rgba(0, 0, 0, 0)');
    });
}

var display_ques = function(move) {
    unmark_all();
    if (!nos.length || !data[curr+1]) return;
    $.ajax({
        type: "POST",
        dataType: 'json',
        url: examUrl,
        data : {flag: 'get', no: nos[curr]},
        success: function(temp) {
            $('#que').text(temp['q']);
            $('#a').text('𝐀.  '+temp['a']);
            $('#b').text('𝐁.  '+temp['b']);
            $('#c').text('𝐂.  '+temp['c']);
            $('#d').text('𝐃.  '+temp['d']);
            $('#queid').text('Question No. '+ (move));
            $('#mark').text('Marks: '+temp['marks']);
            if(data[curr+1].marked != null)
               $('#' + data[curr+1].marked).css("background-color",'rgba(0, 255, 0, 0.6)');
        },
        error: function(error){
            console.log("Here is the error res: " + JSON.stringify(error));
        }
    });
}
var flag_time = true;
function startTimer(duration, display) {
    var timer = duration,hours, minutes, seconds;
    
    timerInterval = setInterval(function () {
        hours = parseInt(timer / 3600 ,10);
        minutes = parseInt((timer%3600) / 60, 10);
        seconds = parseInt(timer % 60, 10);
        hours = hours < 10 ? "0" + hours : hours;
        minutes = minutes < 10 ? "0" + minutes : minutes;
        seconds = seconds < 10 ? "0" + seconds : seconds;

        display.text(hours + ":" + minutes + ":" + seconds);

        if (--timer < 0) {
            finish_test();
            clearInterval(timerInterval);
            flag_time = false;
        }
    }, 1000);
}

function finish_test() {
    save_current_answer(false);
    $('#msg').addClass('alert-info');
    $('#msg').append("Test submitted successfully");
    flag_time = false;
    if (timerInterval) clearInterval(timerInterval);
    if (timeSyncInterval) clearInterval(timeSyncInterval);
    if (typeof window.stopStreaming === 'function') window.stopStreaming();
    $.ajax({
        type: "POST",
        dataType: "json",
        url: examUrl,
        data: {flag: 'completed'},
        success: function(data) {
            if (window.SecureExam) window.SecureExam.end();
            window.location.replace('/student_index');
        },
        error: function(error) {
            console.error("Finish test failed:", error);
            if (window.Swal) {
                Swal.fire('Submit failed', 'Please check your connection and try again.', 'error');
            }
        }
    });    
}

function sendTime() {
    timeSyncInterval = setInterval(function() {
        if(flag_time == false){
            clearInterval(timeSyncInterval);
        }
        var time = $('#time').text();
        var [hh,mm,ss] = time.split(':');
        hh = parseInt(hh);
        mm = parseInt(mm);
        ss = parseInt(ss);
        var seconds = hh*3600 + mm*60 + ss;
        $.ajax({
            type: 'POST',
            dataType: "json",
            url: examUrl,
            data: {flag:'time', time: seconds},
        });
        if(flag_time == false){
            clearInterval(timeSyncInterval);
        }
    }, 5000);
}

$(document).on('click', '#next', function(e){
    e.preventDefault();
    if (!nos.length) return;
    save_current_answer(false);
    if (curr >= nos.length - 1) return;
    curr += 1;
    display_ques(curr+1);
    
});

$(document).on('click', '#prev', function(e){
    e.preventDefault();
    if (!nos.length || curr <= 0) return;
    save_current_answer(false);
    curr -= 1;
    display_ques(curr+1);
    
});

function save_current_answer(markSubmitted) {
    var marked;
    if(flag_time == false){
        return false;
    }
    $('#options td').each(function(i) 
    {
        if($(this).css("background-color") != 'rgba(0, 0, 0, 0)'){
            marked =  $(this).attr('id');
            data[curr+1].marked= marked;
            if (data[curr+1].status === BOOKMARKED || data[curr+1].status === SUBMITTED_BOOKMARKED) {
                data[curr+1].status = SUBMITTED_BOOKMARKED;
            } else if (markSubmitted || data[curr+1].status === MARKED) {
                data[curr+1].status = SUBMITTED;
            }
            $('#question-list').empty();
            ques_grid();
        }
    });
    if (!marked) return false;
    $.ajax({
        type: "POST",
        dataType: 'json',
        url: examUrl,
        data : {flag: 'mark', qid: nos[curr], ans: marked},
        success: function(data) {
            console.log('Answer saved', data);
        },
        error: function(error){
            console.log("Here is the error res: " + JSON.stringify(error));
        }
    });
    return true;
}

$('#submit').on('click', function(e){
    e.preventDefault();
    if (save_current_answer(true) && curr < nos.length - 1) {
        curr += 1;
        display_ques(curr+1);
    }
});

$('#bookmark').on('click', function(e){
    var status = data[curr+1].status;
    if( status == MARKED)
    {
        data[curr+1].status = MARKED_BOOKMARKED;
        $('#question-list').empty();
        ques_grid();
    }
    else if(status == SUBMITTED)
    {
        data[curr+1].status = SUBMITTED_BOOKMARKED;
        $('#question-list').empty();
        ques_grid();
    }
    else
    {
        data[curr+1].status = BOOKMARKED;
        $('#question-list').empty();
        ques_grid();
    }

});



$('#options').on('click', 'td', function(){
    if ($(this).css("background-color") != 'rgba(0, 255, 0, 0.6)') {
        var clicked = $(this).attr('id');
        var que = $('#queid').attr('id');
        unmark_all();
        $(this).css("background-color",'rgba(0, 255, 0, 0.6)');
        if (data[curr+1].status !== SUBMITTED && data[curr+1].status !== SUBMITTED_BOOKMARKED) {
            data[curr+1].status = MARKED;
        }
        data[curr+1].marked = $(this).attr('id');
    }
    else {
        $(this).css("background-color",'rgba(0, 0, 0, 0)');
        data[curr+1].status = NOT_MARKED;
        data[curr+1].marked = null;
    }
});

var submit_overlay_display = true;
$('#finish').on("click", function(e) {
     funSubmitExam();

});

var marked = function() {
    var count = 0;
    for(var i=1;i<=nos.length;i++){
        if(data[i].status == SUBMITTED || data[i].status == SUBMITTED_BOOKMARKED){
            count++;
            $('#question-list').empty();
            ques_grid();
        } 
    }
    return count;
}

var ques_grid = function() {
    document.getElementById("overlay").style.display = "block";
    for(var i=1;i<=nos.length;i++) {
        var color = '';
        var status = data[i].status;
        if(status == NOT_MARKED)
        {
            color = '#1976D2';
        }
        else if(status == SUBMITTED)
        {
            color = '#42ed62';
        }
        else if(status == BOOKMARKED || status == SUBMITTED_BOOKMARKED)
        {
            color = '#e6ed7b';
        }
        else{
            color = '#f44336';
        }
        j = i<10 ? "0" + i: i
        $('#question-list').append('<div class="col-sm-2"><button class="btn btn-primary" style="background-color:' + color + '; color:white;"><div class="question" style="background-color:' + color + '; color:white;">' + j + '</div></div></div>');
    }
    $('.question').click(function() {
        var id = parseInt($(this).text());
        curr = id-1;
        display_ques(curr+1);
    });
}

var make_array = function() {
    for(var i=0; i<nos.length; i++){
        data[i+1] = {marked : null, status: NOT_MARKED}; 
    }
    var txt = document.createElement('textarea');
    txt.innerHTML = answers;
    answers = txt.value;
    try {
        answers = JSON.parse(answers || '{}');
    } catch (err) {
        console.warn('Could not parse saved answers:', err);
        answers = {};
    }
    for(var key in answers) {
        if (data[parseInt(key)+1]) {
            data[parseInt(key)+1].marked = answers[key];
            data[parseInt(key)+1].status = SUBMITTED;
        }
    }
}

function funSubmitExam()
{
    var count = marked();
    var remaining = nos.length - count;
  Swal.fire({
  title: '<strong>FINISH EXAM</strong>',
  icon: 'warning',
  html:
    '<table><tr><td>TOTAL QUESTIONS:</td><td>'+nos.length+'</td></tr><tr><td>ATTEMPTED:</td><td>'+count+'</td></tr><tr><td>REMAINING:</td><td>'+remaining+'</td></tr></table>' ,
  showCloseButton: false,
  showCancelButton: true,
  focusConfirm: true,
  confirmButtonText:
    'OK, FINISH MY EXAM!',
  confirmButtonAriaLabel: 'We are abide by rules!'
}).then((result) => {
  if (result.isConfirmed) {
    finish_test();
  }
})
}

  window.addEventListener('selectstart', function(e){ e.preventDefault(); });
  $(document).ready(function () {
      $('body').bind('select cut copy paste', function (e) {
          e.preventDefault();
      });
      
      $("body").on("contextmenu",function(e){
          return false;
      });
  });

  var lastPrintScreenWarningAt = 0;
  document.addEventListener('keyup', (e) => {
  if (e.key == 'PrintScreen') {
  var now = Date.now();
  if (now - lastPrintScreenWarningAt < 3000) return;
  lastPrintScreenWarningAt = now;
  navigator.clipboard.writeText('');
  alert('Screenshots disabled!');
  }
  });
  
  document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key == 'p') {
  alert('This section is not allowed to print or export to PDF');
  e.cancelBubble = true;
  e.preventDefault();
  e.stopImmediatePropagation();
  }
  });
