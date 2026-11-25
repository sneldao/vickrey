// SPDX-License-Identifier: MIT
pragma solidity ^0.8.30;

import {RealityReceiptsEscrow} from "../src/RealityReceiptsEscrow.sol";

interface Vm {
    function deal(address account, uint256 amount) external;
    function prank(address account) external;
    function warp(uint256 timestamp) external;
    function expectRevert(bytes4 revertData) external;
}

contract RealityReceiptsEscrowTest {
    error ValuesNotEqual();

    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function assertEq(uint256 left, uint256 right) internal pure {
        if (left != right) revert ValuesNotEqual();
    }

    function assertEq(bytes32 left, bytes32 right) internal pure {
        if (left != right) revert ValuesNotEqual();
    }

    function assertEq(address left, address right) internal pure {
        if (left != right) revert ValuesNotEqual();
    }

    RealityReceiptsEscrow private escrow;
    address private operator = address(0xA11CE);
    address private sponsor = address(0x5B01);
    address private observer = address(0x0B5E);
    address private stranger = address(0xBAD);

    bytes32 private challengeId = keccak256("challenge-1");
    bytes32 private submissionId = keccak256("submission-1");
    bytes32 private criteriaHash = keccak256("criteria");
    bytes32 private commitmentHash = keccak256("commitment");
    bytes32 private proofHash = keccak256("proof");
    uint64 private expiry;
    uint256 private amount = 0.01 ether;

    function setUp() public {
        escrow = new RealityReceiptsEscrow(operator);
        expiry = uint64(block.timestamp + 1 hours);
        vm.deal(sponsor, 1 ether);
    }

    function createOpenChallenge() private {
        vm.prank(sponsor);
        escrow.createChallenge{value: amount}(challengeId, criteriaHash, expiry);
    }

    function submitForObserver() private {
        vm.prank(operator);
        escrow.submitEvidenceFor(challengeId, submissionId, commitmentHash, observer);
    }

    function testAcceptedResolutionPaysObserver() public {
        createOpenChallenge();
        submitForObserver();

        uint256 before = observer.balance;
        vm.prank(operator);
        escrow.resolveChallenge(challengeId, RealityReceiptsEscrow.Resolution.Accepted, proofHash);

        assertEq(observer.balance - before, amount);
        RealityReceiptsEscrow.Challenge memory stored = escrow.getChallenge(challengeId);
        assertEq(uint256(stored.state), uint256(RealityReceiptsEscrow.ChallengeState.Resolved));
        assertEq(uint256(stored.resolution), uint256(RealityReceiptsEscrow.Resolution.Accepted));
        assertEq(stored.proofHash, proofHash);
        assertEq(stored.observer, observer);
    }

    function testRejectedResolutionRefundsSponsor() public {
        createOpenChallenge();
        submitForObserver();

        uint256 before = sponsor.balance;
        vm.prank(operator);
        escrow.resolveChallenge(challengeId, RealityReceiptsEscrow.Resolution.Rejected, proofHash);

        assertEq(sponsor.balance - before, amount);
    }

    function testObserverCanSubmitDirectly() public {
        createOpenChallenge();
        vm.prank(observer);
        escrow.submitEvidence(challengeId, submissionId, commitmentHash);

        RealityReceiptsEscrow.Challenge memory stored = escrow.getChallenge(challengeId);
        assertEq(stored.observer, observer);
        assertEq(stored.commitmentHash, commitmentHash);
    }

    function testOnlyOneSubmissionPerChallenge() public {
        createOpenChallenge();
        submitForObserver();

        vm.expectRevert(RealityReceiptsEscrow.SubmissionExists.selector);
        vm.prank(observer);
        escrow.submitEvidence(challengeId, keccak256("other"), commitmentHash);
    }

    function testStrangerCannotResolve() public {
        createOpenChallenge();
        submitForObserver();

        vm.expectRevert(RealityReceiptsEscrow.NotOperator.selector);
        vm.prank(stranger);
        escrow.resolveChallenge(challengeId, RealityReceiptsEscrow.Resolution.Accepted, proofHash);
    }

    function testCannotResolveTwice() public {
        createOpenChallenge();
        submitForObserver();
        vm.prank(operator);
        escrow.resolveChallenge(challengeId, RealityReceiptsEscrow.Resolution.Accepted, proofHash);

        vm.expectRevert(RealityReceiptsEscrow.ChallengeNotOpen.selector);
        vm.prank(operator);
        escrow.resolveChallenge(challengeId, RealityReceiptsEscrow.Resolution.Rejected, proofHash);
    }

    function testExpiredUnresolvedChallengeCanRefundSponsor() public {
        createOpenChallenge();
        vm.warp(expiry);

        uint256 before = sponsor.balance;
        escrow.refundExpired(challengeId);

        assertEq(sponsor.balance - before, amount);
        RealityReceiptsEscrow.Challenge memory stored = escrow.getChallenge(challengeId);
        assertEq(uint256(stored.state), uint256(RealityReceiptsEscrow.ChallengeState.Refunded));
    }

    function testCannotRefundBeforeExpiry() public {
        createOpenChallenge();

        vm.expectRevert(RealityReceiptsEscrow.ChallengeNotExpired.selector);
        escrow.refundExpired(challengeId);
    }

    function testAcceptedResolutionRequiresSubmission() public {
        createOpenChallenge();

        vm.expectRevert(RealityReceiptsEscrow.SubmissionMissing.selector);
        vm.prank(operator);
        escrow.resolveChallenge(challengeId, RealityReceiptsEscrow.Resolution.Accepted, proofHash);
    }

    function testCreateRequiresFutureExpiry() public {
        vm.expectRevert(RealityReceiptsEscrow.InvalidExpiry.selector);
        vm.prank(sponsor);
        escrow.createChallenge{value: amount}(challengeId, criteriaHash, uint64(block.timestamp));
    }
}
