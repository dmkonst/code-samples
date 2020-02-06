const db = require('./database');
var AWS = require('aws-sdk');
var Sendy = require('sendy-api');
var sendy = new Sendy('https://visago-us.sendybay.com/', process.env.sendyAPIkey);
var ses = new AWS.SES({ region: process.env.region});
exports.handler = async (event, context, callback) => {
 console.log(event)
 if (typeof(event.Records[0].body) === "string")
  {
  var body = JSON.parse(event.Records[0].body);
  }
 else if (typeof(event.Records[0].body) === "undefiend") {
  console.log("Event does not contain a payload");
 }
 else {
  var body = event.Records[0].body;
 }
 await get_jobType(body.jobType, body.email, body.status, body.host, body.lang, body.emailTemplate, body.name, body.hash, body.extraData.id);
  
 return {
  'statusCode': 200
 }
};
const get_jobType = async (jobType, email, status, host, lang, mail_type, name, hash, applicantId) => {
 if(jobType == 1){
  try {
   var email_info = await db.query(`Select subject, body from EmailTemplate where lang = ? and type = ? limit 1`, [lang, mail_type]);
  
  }
  catch(e) {
   console.log("MySQL select query failed")
   throw new Error(e)
  }
  let subject = (email_info[0].subject).replace(/{\$application\['firstname'\]}/g, name).replace(/{\$application\['id'\]}/g, applicantId).replace(/\{INSERT APPLICATION NUMBER HERE\}/g, applicantId).replace(/{\$application\['hash'\]}/g, hash)
  let body = (email_info[0].body).replace(/{\$application\['firstname'\]}/g, name).replace(/{\$application\['id'\]}/g, applicantId).replace(/\{INSERT APPLICATION NUMBER HERE\}/g, applicantId).replace(/{\$application\['hash'\]}/g, hash)
  ses_message = ses_msg(subject, body, email)
  let ses_email = await ses.sendEmail(ses_message).promise();
   
  console.log(ses_email)
 } else {
  var subscr_group_name = status + '-' + host + '-' + lang.charAt(0).toUpperCase() + lang.slice(1);
  if(status.slice(-1) == 1) {
   //Subscribe
   try {
    var id_subscribe_group = await db.query(`Select sendy_list_id from SendyLists where list_name = ? limit 1`, [subscr_group_name]);
    var params = {
     email: email,
     name: name,
     list_id: id_subscribe_group[0].sendy_list_id
    }
    subscription = await new Promise ( (resolve,reject) => { sendy.subscribe(params, function(err, result) {
     if (err) {
      if (err.toString() == 'Error: \n1') {
       console.log('User either is not yet in Sendy \n or User has not yet confirmed the double opt in \n or User has previously unsubscribed from Sendy')
       console.log(`${email} has been subscribed to ${subscr_group_name}`);
       resolve();
      }
      else {
       console.log(err.toString());
       reject();
      }
     }
     else {
     console.log(`${email} has been subscribed to ${subscr_group_name}`);
     resolve()
     }
    });
     });
     
   }
   catch (e) {
    throw new Error(e)
   }
  } 
  if(status.slice(-1) > 1 && status.slice(-1) < 5) {
   var status_to_unsubscr = status.slice(0, -1) + (parseInt(status.slice(-1), 10) - 1)
   var group_to_unsubscr = status_to_unsubscr + '-' + host + '-' + lang.charAt(0).toUpperCase() + lang.slice(1);
   //Unsubscribe
   try {
    var id_unsubscribe_group = await db.query(`Select sendy_list_id from SendyLists where list_name = ? limit 1`, [group_to_unsubscr]);
     
    var params = {
     email: email,
     list_id: id_unsubscribe_group[0].sendy_list_id
    }
    unsubscribe = await new Promise ( (resolve,reject) => { sendy.unsubscribe(params, function(err, result) {
     if (err) {
      if (err.toString() == 'Error: \n1') {
       console.log('User either is not yet in Sendy \n or User has not yet confirmed the double opt in \n or User has previously unsubscribed from Sendy')
       console.log(`${email} has been unsubscribed to ${group_to_unsubscr}`);
       resolve();
      }
      else if (err.toString() == 'Error: \nEmail does not exist.') {
       console.log("Email doesn't exist")
       resolve();
      }
      else {
       console.log(err.toString());
       reject();
      }
     }
     else {
      console.log(`${email} has been unsubscribed to ${group_to_unsubscr}`);
      resolve();
      }
    });
   });
   }
   catch (e) {
    throw new Error(e)
   }
   //Subscribe
   try {
    var id_subscribe_group = await db.query(`Select sendy_list_id from SendyLists where list_name = ? limit 1`, [subscr_group_name]);
    var params = {
     email: email,
     name: name,
     list_id: id_subscribe_group[0].sendy_list_id
    }
    subscription = await new Promise ( (resolve,reject) => { sendy.subscribe(params, function(err, result) {
     if (err) {
      if (err.toString() == 'Error: \n1') {
       console.log('User either is not yet in Sendy \n or User has not yet confirmed the double opt in \n or User has previously unsubscribed from Sendy')
       console.log(`${email} has been subscribed to ${subscr_group_name}`);
       resolve();
      }
      else if (err.toString() == 'Error: \nAlready subscribed.') {
       console.log("User has already subscribed")
       resolve();
      }
      else {
       console.log(err.toString());
       reject();
      }
      }
     else {
      console.log(`${email} has been subscribed to ${subscr_group_name}`);
      resolve();
     }
    });
   });
   }
   catch (e) {
    throw new Error(e)
   }
  }
 }
};
const ses_msg = (subject, body, email) => {
 var params = {
  Destination: {
   ToAddresses: [email]
  },
  Message: {
   Body: {
    Html: {
     Charset: 'UTF-8',
     Data: body
    }
   },
   Subject: {
    Data: subject,
    Charset: 'UTF-8'
   }
  },
  Source: process.env.from_email
 };
 return params;
}
