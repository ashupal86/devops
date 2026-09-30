# ============================================================
# VPC
# ============================================================

resource "aws_vpc" "main" {
  cidr_block = local.vpc_cidr

  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = local.name
  }
}

# ============================================================
# INTERNET GATEWAY
# ============================================================

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name}-igw"
  }
}

# ============================================================
# PUBLIC SUBNETS
# ============================================================
#
# EKS worker nodes live here.
#
# We intentionally do NOT create a NAT Gateway.
# This saves a significant recurring AWS cost.
# ============================================================

resource "aws_subnet" "public" {
  count = 2

  vpc_id = aws_vpc.main.id

  cidr_block = local.public_subnet_cidrs[count.index]

  availability_zone = data.aws_availability_zones.available.names[count.index]

  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name}-public-${count.index + 1}"

    "kubernetes.io/role/elb" = "1"

    "kubernetes.io/cluster/${local.name}" = "shared"
  }
}

# ============================================================
# PRIVATE SUBNETS
# ============================================================
#
# RDS lives here.
#
# There is no route to the Internet.
# ============================================================

resource "aws_subnet" "private" {
  count = 2

  vpc_id = aws_vpc.main.id

  cidr_block = local.private_subnet_cidrs[count.index]

  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "${local.name}-private-${count.index + 1}"

    "kubernetes.io/role/internal-elb" = "1"

    "kubernetes.io/cluster/${local.name}" = "shared"
  }
}

# ============================================================
# PUBLIC ROUTE TABLE
# ============================================================

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"

    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${local.name}-public"
  }
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id = aws_subnet.public[count.index].id

  route_table_id = aws_route_table.public.id
}

# ============================================================
# PRIVATE ROUTE TABLE
# ============================================================
#
# Deliberately no NAT Gateway.
# ============================================================

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name}-private"
  }
}

resource "aws_route_table_association" "private" {
  count = 2

  subnet_id = aws_subnet.private[count.index].id

  route_table_id = aws_route_table.private.id
}
