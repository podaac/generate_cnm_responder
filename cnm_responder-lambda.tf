# AWS Lambda function
resource "aws_lambda_function" "aws_lambda_cnm_responder" {
  filename         = "cnm_responder.zip"
  function_name    = "${var.prefix}-cnm-responder"
  role             = aws_iam_role.aws_lambda_execution_role.arn
  handler          = "cnm_responder.cnm_handler"
  runtime          = "python3.9"
  source_code_hash = filebase64sha256("cnm_responder.zip")
  timeout          = 300
  vpc_config {
    subnet_ids         = data.aws_subnets.private_application_subnets.ids
    security_group_ids = data.aws_security_groups.vpc_default_sg.ids
  }
  file_system_config {
    arn              = data.aws_efs_access_points.aws_efs_generate_ap.arns[2]
    local_mount_path = "/mnt/data"
  }
}

resource "aws_lambda_permission" "aws_lambda_cnm_responder_sns" {
  statement_id  = "AllowExecutionFromSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.aws_lambda_cnm_responder.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = data.aws_sns_topic.cnm_response.arn
}

# CNM Response topic subscription
resource "aws_sns_topic_subscription" "sns-topic" {
  topic_arn = data.aws_sns_topic.cnm_response.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.aws_lambda_cnm_responder.arn
}

# AWS Lambda role and policy
resource "aws_iam_role" "aws_lambda_execution_role" {
  name = "${var.prefix}-lambda-cnm-responder-execution-role"
  assume_role_policy = jsonencode({
    "Version" : "2012-10-17",
    "Statement" : [
      {
        "Effect" : "Allow",
        "Principal" : {
          "Service" : "lambda.amazonaws.com"
        },
        "Action" : "sts:AssumeRole"
      }
    ]
  })
  permissions_boundary = "arn:aws:iam::${local.account_id}:policy/NGAPShRoleBoundary"
}

resource "aws_iam_role_policy_attachment" "aws_lambda_execution_role_policy_attach" {
  role       = aws_iam_role.aws_lambda_execution_role.name
  policy_arn = aws_iam_policy.aws_lambda_execution_policy.arn
}

resource "aws_iam_policy" "aws_lambda_execution_policy" {
  name        = "${var.prefix}-lambda-cnm-responder-execution-policy"
  description = "Write to CloudWatch logs, list and delete from S3."
  policy = jsonencode({
    "Version" : "2012-10-17",
    "Statement" : [
      {
        "Sid" : "AllowCreatePutLogs",
        "Effect" : "Allow",
        "Action" : [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        "Resource" : "arn:aws:logs:*:*:*"
      },
      {
        "Sid" : "AllowVPCAccess",
        "Effect" : "Allow",
        "Action" : [
          "ec2:CreateNetworkInterface"
        ],
        "Resource" : concat([for subnet in data.aws_subnet.private_application_subnet : subnet.arn], ["arn:aws:ec2:${var.aws_region}:${local.account_id}:*/*"])
      },
      {
        "Sid" : "AllowVPCDelete",
        "Effect" : "Allow",
        "Action" : [
          "ec2:DeleteNetworkInterface"
        ],
        "Resource" : "arn:aws:ec2:${var.aws_region}:${local.account_id}:*/*"
      },
      {
        "Sid" : "AllowVPCDescribe",
        "Effect" : "Allow",
        "Action" : [
          "ec2:DescribeNetworkInterfaces",
        ],
        "Resource" : "*"
      },
      {
        "Sid" : "AllowEFSAccess",
        "Effect" : "Allow",
        "Action" : [
          "elasticfilesystem:ClientMount",
          "elasticfilesystem:ClientWrite",
          "elasticfilesystem:ClientRootAccess"
        ],
        "Resource" : "${data.aws_efs_access_points.aws_efs_generate_ap.arns[2]}"
      },
      {
        "Sid" : "AllowListBucket",
        "Effect" : "Allow",
        "Action" : [
          "s3:ListBucket"
        ],
        "Resource" : "${data.aws_s3_bucket.l2p_granules.arn}"
      },
      {
        "Sid" : "AllowGetDeleteObject",
        "Effect" : "Allow",
        "Action" : [
          "s3:DeleteObject"
        ],
        "Resource" : "${data.aws_s3_bucket.l2p_granules.arn}/*"
      }
    ]
  })
}